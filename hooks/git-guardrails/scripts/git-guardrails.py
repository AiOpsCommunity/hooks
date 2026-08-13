#!/usr/bin/env python3
"""PreToolUse hook: stop irreversible git operations before they run.

Only blocks things that destroy work that is not recoverable through normal git
means: force pushes to protected branches, hard resets over uncommitted changes,
deleting protected branches, wiping untracked files, and history rewrites.

Everything else passes. A guardrail that fires on ordinary work gets uninstalled
within a day, so the bar for blocking is "this loses work permanently".

Exits 2 with the reason on stderr when it blocks, which is what sends the reason
back to Claude. Fails open on anything unexpected.

Config, optional, at .claude/git-guardrails.json in the project:

    {
      "protectedBranches": ["main", "master", "production", "release/*"],
      "allowForceWithLease": true,
      "blockCommitOnProtected": true
    }
"""

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys

DEFAULTS = {
    "protectedBranches": ["main", "master", "production", "prod", "release/*"],
    # --force-with-lease refuses to clobber commits you have not seen, so it is
    # allowed on feature branches by default. Protected branches still block.
    "allowForceWithLease": True,
    "blockCommitOnProtected": True,
}

# Tokens that separate one command from the next.
OPERATORS = {"&&", "||", ";", "|", "&", "(", ")"}

# NAME=value prefixes: `GIT_DIR=.git git push` is still a git push.
ENV_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Wrappers that pass the rest of the line through to another command.
WRAPPERS = {"sudo", "nice", "nohup", "time", "env", "command", "xargs"}


def git_commands(command):
    """Split a shell command line into the git invocations it contains.

    Tokenising comes first, splitting on operators second. Doing it the other
    way round cuts straight through quoted arguments: `git commit -m 'fix; done'`
    becomes the fragment `git commit -m 'fix`, shlex refuses it, and the whole
    command escapes every check below. That failure was silent, which is the
    worst property a guardrail can have.

    punctuation_chars makes the lexer treat `;`, `&&` and friends as their own
    tokens even without surrounding spaces, so `a;git push` splits correctly
    while `-m 'fix; done'` stays one argument.

    Returns a list of token lists, each starting at the git executable.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        # shlex treats # as a comment marker by default; a shell only does that
        # at the start of a word. Leaving it on would silently truncate
        # `git commit -m fix#123` and skip everything after it.
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return []

    segments = []
    current = []
    for token in tokens:
        if token in OPERATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)

    out = []
    for segment in segments:
        # Strip NAME=value prefixes and wrapper programs until the real command.
        while segment and (ENV_PREFIX.match(segment[0])
                           or os.path.basename(segment[0]) in WRAPPERS):
            segment = segment[1:]
        if len(segment) >= 2 and os.path.basename(segment[0]) == "git":
            out.append(segment)
    return out


def load_config(cwd):
    cfg = dict(DEFAULTS)
    path = os.path.join(cwd, ".claude", "git-guardrails.json")
    try:
        with open(path) as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def git(cwd, *args):
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def is_protected(branch, patterns):
    if not branch:
        return False
    return any(fnmatch.fnmatch(branch, p) for p in patterns)


def block(reason, suggestion):
    print(f"Blocked by git-guardrails: {reason}\n{suggestion}", file=sys.stderr)
    sys.exit(2)


def check_push(tokens, cwd, cfg, current):
    forced = any(t in ("--force", "-f") for t in tokens)
    lease = any(t.startswith("--force-with-lease") for t in tokens)

    if not (forced or lease):
        return

    # Target branch: last non-flag token after the remote, else current branch.
    args = [t for t in tokens[2:] if not t.startswith("-")]
    target = args[1] if len(args) >= 2 else current
    target = target.split(":")[-1] if target else target

    if is_protected(target, cfg["protectedBranches"]):
        block(
            f"force push to protected branch '{target}'",
            "Push to a feature branch and open a pull request. If this is "
            "genuinely intended, run it yourself outside Claude Code.",
        )

    if forced and not lease and not cfg["allowForceWithLease"]:
        block(
            f"force push to '{target}'",
            "Use --force-with-lease, which refuses to overwrite commits you "
            "have not seen.",
        )

    if forced and not lease:
        # Allowed, but say something useful.
        print(
            "git-guardrails: prefer --force-with-lease over --force.",
            file=sys.stderr,
        )


def check_delete_branch(tokens, cfg):
    if "-D" in tokens or ("-d" in tokens and "--force" in tokens):
        for t in tokens[2:]:
            if not t.startswith("-") and is_protected(t, cfg["protectedBranches"]):
                block(
                    f"deleting protected branch '{t}'",
                    "Protected branches are deleted by a human, not by an agent.",
                )


def check_reset(tokens, cwd):
    if "--hard" not in tokens:
        return
    dirty = git(cwd, "status", "--porcelain")
    if dirty:
        count = len(dirty.splitlines())
        block(
            f"git reset --hard with {count} uncommitted change(s)",
            "Run `git stash` first, or commit to a scratch branch. The changes "
            "cannot be recovered after a hard reset.",
        )


def has_force_flag(tokens):
    """True when -f or --force is present, without matching an f inside a value.

    Concatenating every dash-prefixed token and searching for "f" reads the f of
    `--exclude=foo` as the force flag, which blocks `git clean -nd --exclude=foo`
    — a dry run that deletes nothing.
    """
    for token in tokens:
        if token == "--force":
            return True
        if re.fullmatch(r"-[a-zA-Z]+", token) and "f" in token:
            return True
    return False


def check_clean(tokens, cwd):
    # -n / --dry-run only lists what would go; nothing is deleted.
    if "-n" in tokens or "--dry-run" in tokens:
        return
    if not has_force_flag(tokens):
        return
    untracked = git(cwd, "clean", "-nd")
    if untracked:
        count = len(untracked.splitlines())
        block(
            f"git clean would delete {count} untracked path(s)",
            "Untracked files are not in git and cannot be recovered. Review "
            "`git clean -nd` output first.",
        )


def check_commit(tokens, cwd, cfg, current):
    if not cfg["blockCommitOnProtected"]:
        return
    if is_protected(current, cfg["protectedBranches"]):
        block(
            f"committing directly to protected branch '{current}'",
            f"Create a branch first: git checkout -b <name>. Current branch is "
            f"'{current}'.",
        )


def check_history_rewrite(tokens):
    """Match on the subcommand, not on the text of the line.

    Searching the whole command for "filter-branch" blocks
    `git commit -m 'stop using filter-branch'`, which rewrites nothing. The
    subcommand is the only place these can actually appear as an instruction.
    """
    advice = "History rewrites are a human decision. Run it yourself if you are sure."
    sub = tokens[1]
    rest = tokens[2:]

    if sub == "filter-branch":
        block("`git filter-branch` rewrites every commit", advice)

    if sub == "reflog" and rest and rest[0] == "expire":
        block(
            "`git reflog expire` destroys the reflog, the last recovery route",
            advice,
        )

    if sub == "gc":
        for token in rest:
            # --prune=never is the safe one; now/all drop unreachable objects.
            if token.startswith("--prune=") and token != "--prune=never":
                block(f"`git gc {token}` drops unreachable objects immediately", advice)

    if sub == "update-ref" and "-d" in rest:
        block("`git update-ref -d` deletes a ref directly", advice)


def check_checkout_discard(tokens):
    # git checkout . / git restore . discards every uncommitted change
    if tokens[-1] not in (".", "--", "*"):
        return
    if "-b" in tokens:
        return
    # --staged / --cached unstage only: the index changes, the working tree does
    # not, and nothing is lost. Blocking those is a false positive.
    staged_only = ("--staged" in tokens or "--cached" in tokens)
    if staged_only and "--worktree" not in tokens and "-W" not in tokens:
        return
    block(
        f"`{' '.join(tokens)}` discards all uncommitted changes",
        "Stash first if there is anything worth keeping.",
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError):
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or "git" not in command:
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    cfg = load_config(cwd)
    current = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")

    for tokens in git_commands(command):
        check_history_rewrite(tokens)

        sub = tokens[1]
        if sub == "push":
            check_push(tokens, cwd, cfg, current)
        elif sub == "branch":
            check_delete_branch(tokens, cfg)
        elif sub == "reset":
            check_reset(tokens, cwd)
        elif sub == "clean":
            check_clean(tokens, cwd)
        elif sub == "commit":
            check_commit(tokens, cwd, cfg, current)
        elif sub in ("checkout", "restore"):
            check_checkout_discard(tokens)

    sys.exit(0)


if __name__ == "__main__":
    main()
