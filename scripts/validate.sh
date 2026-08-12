#!/usr/bin/env bash
#
# validate.sh - structural checks for this repo. Run before opening a PR.
# CI runs the same script, so a green run here means a green run there.
#
# Fails on (these break installation or violate the rules):
#   - marketplace.json invalid, or a plugin source that does not exist
#   - a hook missing plugin.json, hooks/hooks.json or README.md
#   - plugin.json name not matching the folder, or missing required fields
#   - unknown hook event names
#   - commands not using "${CLAUDE_PLUGIN_ROOT}", or containing a personal path
#   - script paths escaping the plugin directory
#   - referenced scripts missing, not executable, or without a shebang
#   - a hook on disk that is not listed in marketplace.json
#   - _template being structurally broken
#
# Warns on (worth a look, does not block):
#   - a hook command without a timeout
#   - a version that is not semver
#
# It cannot tell you whether a hook is a good idea or safe to run. Read the diff
# for that; see CONTRIBUTING.md for what gets rejected on review.

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root" || exit 1

python3 - <<'PY'
import json
import os
import re
import sys

# Known events, from https://code.claude.com/docs/en/hooks. This list is a
# convenience, not a gate: an event missing here is a warning, never a failure.
# Claude Code ships new events regularly, and a validator that rejects a hook
# because its own list is a release behind blocks work it has no business
# blocking. A typo still gets noticed, which is the point.
EVENTS = {
    # session
    "SessionStart", "SessionEnd", "Setup",
    # per turn
    "UserPromptSubmit", "UserPromptExpansion", "Stop", "StopFailure",
    # tools
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
    "PermissionDenied", "PostToolBatch",
    # notification and display
    "Notification", "MessageDisplay",
    # subagents and tasks
    "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted",
    "TeammateIdle",
    # configuration and files
    "ConfigChange", "InstructionsLoaded", "CwdChanged", "DirectoryAdded",
    "FileChanged",
    # worktrees and compaction
    "WorktreeCreate", "WorktreeRemove", "PreCompact", "PostCompact",
    # MCP
    "Elicitation", "ElicitationResult",
}

REQUIRED_MANIFEST_FIELDS = ("name", "description", "version")
SEMVER = re.compile(r"^\d+\.\d+\.\d+")

fail = False
warned = False


def err(msg):
    global fail
    print(f"  FAIL: {msg}", file=sys.stderr)
    fail = True


def warn(msg):
    global warned
    print(f"  warn: {msg}")
    warned = True


def ok(msg):
    print(f"  ok: {msg}")


def script_path_from(hook):
    """Extract the bundled script a hook runs, relative to the plugin root.

    Two forms exist. Exec form puts the interpreter in `command` and the script
    in `args`, and spawns it without a shell:

        {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/x.py"]}

    Shell form puts everything in `command` and hands it to sh -c:

        {"command": "\\"${CLAUDE_PLUGIN_ROOT}\\"/scripts/x.py"}

    Returns None when no bundled script is referenced.
    """
    parts = []
    if isinstance(hook.get("args"), list):
        parts = [a for a in hook["args"] if isinstance(a, str)]
    if not parts:
        parts = [hook.get("command", "")]

    for part in parts:
        if "CLAUDE_PLUGIN_ROOT" not in part:
            continue
        tail = part.split("}", 1)[-1]
        tail = tail.strip().strip('"').strip()
        if not tail:
            continue
        return tail.split()[0].lstrip("/")
    return None


def check_scripts(base, cfg, label):
    """Check every command in a hooks.json: variable use, path safety, script sanity."""
    for event, groups in (cfg.get("hooks") or {}).items():
        if event not in EVENTS:
            warn(
                f"{label}: '{event}' is not in this script's list of known events. "
                "If the docs list it, add it to EVENTS; if not, check the spelling"
            )
        else:
            ok(f"{label}: event {event}")

        if not isinstance(groups, list):
            err(f"{label}: event '{event}' must hold a list")
            continue

        for group in groups:
            for hook in group.get("hooks", []):
                if hook.get("type") != "command":
                    continue

                command = hook.get("command", "")
                args = hook.get("args") if isinstance(hook.get("args"), list) else []
                whole = " ".join([command] + [a for a in args if isinstance(a, str)])

                if "CLAUDE_PLUGIN_ROOT" not in whole:
                    err(f"{label}: nothing uses ${{CLAUDE_PLUGIN_ROOT}}: {whole}")
                if "/Users/" in whole or "/home/" in whole or "C:\\" in whole:
                    err(f"{label}: a personal path is hard-coded: {whole}")
                if "timeout" not in hook:
                    warn(f"{label}: no timeout on the {event} command")

                rel = script_path_from(hook)
                if not rel:
                    continue

                if ".." in rel.split("/"):
                    err(f"{label}: script path escapes the plugin directory: {rel}")
                    continue

                script = os.path.join(base, rel)
                if not os.path.isfile(script):
                    err(f"{label}: script {rel} not found")
                    continue
                if not os.access(script, os.X_OK):
                    err(f"{label}: script {rel} is not executable (chmod +x)")
                    continue

                with open(script, "rb") as fh:
                    if not fh.read(2) == b"#!":
                        err(f"{label}: script {rel} has no shebang")
                        continue

                ok(f"{label}: script {rel} is executable and has a shebang")


def check_monitors(base, entries, label):
    """Check a monitors.json: shape, required fields, and any bundled script.

    A monitor is a long-lived background command whose stdout reaches Claude as
    notifications, so the bar is the same as for hooks. Unlike a hook it often
    runs a plain shell command (`tail -F ...`) rather than a bundled script, so
    ${CLAUDE_PLUGIN_ROOT} is required only when it does reference one.
    """
    if not isinstance(entries, list):
        err(f"{label}: monitors.json must contain a JSON array")
        return
    if not entries:
        err(f"{label}: monitors.json is empty")
        return

    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            err(f"{label}: every monitor must be an object")
            continue

        name = entry.get("name")
        command = entry.get("command", "")
        for field in ("name", "command", "description"):
            if not entry.get(field):
                err(f"{label}: a monitor has no {field}")

        if name:
            if name in seen:
                err(f"{label}: two monitors are both called '{name}'")
            seen.add(name)

        when = entry.get("when")
        if when is not None and when != "always" and not when.startswith("on-skill-invoke:"):
            err(
                f"{label}: monitor '{name}' has when='{when}'; only 'always' or "
                "'on-skill-invoke:<skill>' are valid"
            )

        # Documented as rejected: a monitor command runs through a shell, so
        # Claude Code refuses to substitute user config into it.
        if "${user_config." in command:
            err(
                f"{label}: monitor '{name}' references ${{user_config.*}}, which "
                "Claude Code rejects for shell commands. Read the value from a "
                "config file in the script instead"
            )

        if "/Users/" in command or "/home/" in command or "C:\\" in command:
            err(f"{label}: monitor '{name}' hard-codes a personal path: {command}")

        if "CLAUDE_PLUGIN_ROOT" not in command:
            ok(f"{label}: monitor {name} (no bundled script)")
            continue

        rel = script_path_from({"command": command})
        if not rel:
            continue
        if ".." in rel.split("/"):
            err(f"{label}: monitor '{name}' escapes the plugin directory: {rel}")
            continue

        script = os.path.join(base, rel)
        if not os.path.isfile(script):
            err(f"{label}: monitor '{name}' script {rel} not found")
        elif not os.access(script, os.X_OK):
            err(f"{label}: monitor '{name}' script {rel} is not executable (chmod +x)")
        else:
            with open(script, "rb") as fh:
                if fh.read(2) != b"#!":
                    err(f"{label}: monitor '{name}' script {rel} has no shebang")
                else:
                    ok(f"{label}: monitor {name} runs {rel}")


def check_manifest(base, name):
    """Manifest checks shared by hooks and monitors."""
    manifest = load_json(os.path.join(base, ".claude-plugin", "plugin.json"), name)
    if manifest is None:
        return
    for field in REQUIRED_MANIFEST_FIELDS:
        if not manifest.get(field):
            err(f"{name}: plugin.json has no {field}")
    if manifest.get("name") != name:
        err(f"{name}: plugin.json name '{manifest.get('name')}' != folder '{name}'")
    else:
        ok("plugin.json name matches folder")
    version = str(manifest.get("version", ""))
    if version and not SEMVER.match(version):
        warn(f"{name}: version '{version}' is not semver")


def load_json(path, label):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        err(f"{label}: missing {path}")
    except json.JSONDecodeError as exc:
        err(f"{label}: {os.path.basename(path)} is invalid JSON: {exc}")
    return None


# ---------------------------------------------------------------- marketplace

print("marketplace.json")
mp = load_json(".claude-plugin/marketplace.json", "marketplace")
if mp is None:
    sys.exit(1)
ok("valid JSON")

listed = {}
for entry in mp.get("plugins", []):
    name, source = entry.get("name"), entry.get("source")
    if not name or not source:
        err(f"marketplace: entry missing name or source: {entry}")
        continue
    listed[name] = source
    if not os.path.isdir(source):
        err(f"marketplace: {name} points at {source}, which does not exist")
    if not entry.get("description"):
        err(f"marketplace: {name} has no description")

# Hooks and monitors are both plugins and are checked the same way. Only the
# config file inside them differs, so the loop is shared.
KINDS = (
    ("hooks", os.path.join("hooks", "hooks.json")),
    ("monitors", os.path.join("monitors", "monitors.json")),
)


def check_config(base, kind, cfg, label):
    if kind == "hooks":
        if not (cfg.get("hooks") or {}):
            err(f"{label}: hooks.json registers no events")
        check_scripts(base, cfg, label)
    else:
        check_monitors(base, cfg, label)


all_on_disk = set()

for kind, config_rel in KINDS:
    if not os.path.isdir(kind):
        continue

    tpl = os.path.join(kind, "_template")
    print(f"\n{tpl}")
    if not os.path.isdir(tpl):
        err(f"the {kind} template is missing; contributors start from it")
    else:
        # The template is not a real plugin: its name intentionally differs from
        # the folder and it is not in the marketplace. Everything else must
        # still hold, or people copy a broken starting point.
        manifest = load_json(os.path.join(tpl, ".claude-plugin", "plugin.json"), "_template")
        cfg = load_json(os.path.join(tpl, config_rel), "_template")
        if manifest is not None and cfg is not None:
            ok("manifest and config are valid JSON")
            check_config(tpl, kind, cfg, f"{kind}/_template")
        if "_template" in listed:
            err("_template must not be listed in marketplace.json")

    on_disk = sorted(
        d for d in os.listdir(kind)
        if os.path.isdir(os.path.join(kind, d)) and not d.startswith("_")
    )
    all_on_disk.update(on_disk)

    if not on_disk:
        print(f"\nno {kind} yet")

    for name in on_disk:
        print(f"\n{kind}/{name}")
        base = os.path.join(kind, name)

        if name not in listed:
            err(f"{name} is not listed in marketplace.json")

        if not os.path.isfile(os.path.join(base, "README.md")):
            err(f"{name}: missing README.md")

        check_manifest(base, name)

        cfg = load_json(os.path.join(base, config_rel), name)
        if cfg is not None:
            check_config(base, kind, cfg, name)

for orphan in sorted(set(listed) - all_on_disk):
    err(f"marketplace lists {orphan}, but no hooks/{orphan} or monitors/{orphan} exists")

print()
if fail:
    print("validation failed", file=sys.stderr)
    sys.exit(1)
print("all checks passed" + (" (with warnings)" if warned else ""))
PY
