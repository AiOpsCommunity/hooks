#!/usr/bin/env python3
"""Stop hook: collect candidate CLAUDE.md lines from the session that just ended.

Writes to .claude/claude-md-inbox.md and never touches CLAUDE.md itself. That
separation is deliberate: a hook that silently edits a git-tracked file which
goes into every prompt is the kind of thing people uninstall. The companion
skill reviews the inbox, verifies each candidate against the codebase, and
proposes a diff that you approve.

Signals, all deterministic, no model call:

  1. A shell command that failed and was then re-run in a changed form that
     succeeded. The working form is the thing worth writing down.
  2. A correction from the user, recognised by an opening negation followed by
     an instruction ("nee, we gebruiken ddev", "no, use pnpm").
  3. A search that repeated: the same glob or grep pattern issued three or more
     times in one session, which means the answer was never obvious.

Run with --dump <path> to write the raw payload instead, which is how you find
out what the Stop event actually gives you on your Claude Code version.
"""

import json
import os
import re
import subprocess
import sys
from datetime import date

MAX_CANDIDATES = 12
INBOX = os.path.join(".claude", "claude-md-inbox.md")

CORRECTION = re.compile(
    r"^\s*(nee|nope|no|niet|not|actually|wrong|fout)\b[,.!\s]+(.{10,200})",
    re.IGNORECASE,
)

ERROR_MARKER = re.compile(
    r"(command not found|no such file|not recognized|permission denied|"
    r"error|failed|fatal|exit code [1-9]|non-zero)",
    re.IGNORECASE,
)

# Commands too generic to be worth recording.
BORING = re.compile(r"^\s*(ls|cd|cat|echo|pwd|which|git status|git diff|git log)\b")


def dump_mode(payload):
    path = sys.argv[sys.argv.index("--dump") + 1]
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    sys.exit(0)


def read_transcript(path):
    """Return a list of transcript entries, or [] if unreadable.

    The transcript format is not a stable public API, so every access is
    defensive and any failure means we simply produce no candidates.
    """
    entries = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return entries


def walk_text(node, out):
    """Collect strings from an arbitrarily shaped message payload."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            walk_text(value, out)
    elif isinstance(node, list):
        for value in node:
            walk_text(value, out)


def message_text(entry):
    """Best-effort extraction of the content of one transcript entry."""
    node = entry.get("message", entry)
    if isinstance(node, dict) and "content" in node:
        node = node["content"]
    out = []
    walk_text(node, out)
    return "\n".join(out)


def collect(entries):
    """Return (commands, corrections, searches).

    commands is a list of (command, failed). Failure lives in a later entry than
    the command itself, since the tool result arrives afterwards, so the next two
    entries are checked for error markers.
    """
    texts = []
    for entry in entries:
        role = entry.get("role") or (entry.get("message") or {}).get("role")
        try:
            raw = json.dumps(entry)
        except (TypeError, ValueError):
            raw = ""
        texts.append((role, message_text(entry), raw))

    commands = []
    corrections = []
    searches = {}

    for index, (role, text, raw) in enumerate(texts):
        lookahead = " ".join(t for _, t, _ in texts[index + 1:index + 3])

        if role == "user":
            for line in text.splitlines():
                match = CORRECTION.match(line.strip())
                if match:
                    corrections.append(" ".join(line.split())[:200])
                    break

        for found in re.finditer(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"', raw):
            command = found.group(1).encode().decode("unicode_escape").strip()
            if command and not BORING.match(command):
                commands.append((command, bool(ERROR_MARKER.search(lookahead))))

        for found in re.finditer(r'"pattern"\s*:\s*"((?:[^"\\]|\\.)*)"', raw):
            key = found.group(1)
            searches[key] = searches.get(key, 0) + 1

    return commands, corrections, searches


def fixed_commands(commands):
    """Pairs where a failing command was followed by a working variant.

    The fix usually adds a prefix rather than changing the program: `phpunit`
    becomes `ddev exec vendor/bin/phpunit`, `tsc` becomes `npx tsc`. Matching on
    the basename of the program catches that, where a prefix match would not.
    """
    out = []
    for index, (command, failed) in enumerate(commands):
        if not failed or not command.split():
            continue
        program = os.path.basename(command.split()[0])
        for later, later_failed in commands[index + 1:]:
            if later_failed or later == command:
                continue
            if program and program in later:
                out.append((command, later))
                break
    return out


def ensure_ignored(cwd):
    """Make sure the inbox is not about to be committed.

    The inbox holds verbatim shell commands and things you typed at Claude, so
    it should never reach a remote. Plenty of teams commit .claude/ on purpose
    (it is where project-level Claude config lives), so being inside that
    directory is not protection.

    The line goes into .git/info/exclude rather than .gitignore: same effect for
    this clone, but it does not modify a tracked file that everyone else on the
    project would see change. A hook editing .gitignore behind your back is the
    kind of surprise that gets a hook uninstalled.

    Best effort. Not being able to do this is not a reason to lose the capture.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd, capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return  # not a git repo, nothing to exclude it from
        git_dir = os.path.join(cwd, result.stdout.strip())

        already = subprocess.run(
            ["git", "check-ignore", "-q", INBOX],
            cwd=cwd, capture_output=True, timeout=3,
        )
        if already.returncode == 0:
            return  # already ignored, by .gitignore or otherwise

        exclude = os.path.join(git_dir, "info", "exclude")
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        existing = ""
        if os.path.isfile(exclude):
            with open(exclude) as fh:
                existing = fh.read()
        if INBOX in existing:
            return
        with open(exclude, "a") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(
                "\n# added by claude-md-maintainer: holds session text, "
                "not for committing\n"
                f"{INBOX}\n"
            )
    except (OSError, subprocess.SubprocessError):
        return


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError):
        sys.exit(0)

    if "--dump" in sys.argv:
        dump_mode(payload)

    # Do not re-run when the stop hook itself continued the session.
    if payload.get("stop_hook_active"):
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    transcript = payload.get("transcript_path")

    candidates = []

    if transcript and os.path.isfile(transcript):
        commands, corrections, searches = collect(read_transcript(transcript))

        for broken, working in fixed_commands(commands)[:5]:
            candidates.append(
                f"- [command] `{working}` works here; `{broken}` failed first"
            )

        for correction in corrections[:5]:
            candidates.append(f"- [correction] {correction}")

        for pattern, count in sorted(searches.items(), key=lambda kv: -kv[1]):
            if count >= 3:
                candidates.append(
                    f"- [repeated search] looked for `{pattern}` {count} times"
                )

    if not candidates:
        sys.exit(0)

    inbox = os.path.join(cwd, INBOX)
    ensure_ignored(cwd)
    try:
        os.makedirs(os.path.dirname(inbox), exist_ok=True)
        existing = ""
        if os.path.isfile(inbox):
            with open(inbox) as fh:
                existing = fh.read()

        new = [c for c in candidates[:MAX_CANDIDATES] if c not in existing]
        if not new:
            sys.exit(0)

        with open(inbox, "a") as fh:
            if not existing:
                fh.write(
                    "# CLAUDE.md inbox\n\n"
                    "Candidates captured automatically at the end of a session. "
                    "Nothing here is in CLAUDE.md yet.\n"
                    "Ask Claude to review the inbox, or delete lines you do not "
                    "want. This file is gitignored.\n"
                )
            fh.write(f"\n## {date.today().isoformat()}\n\n")
            fh.write("\n".join(new) + "\n")
    except OSError:
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
