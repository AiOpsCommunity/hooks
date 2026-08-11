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

# Keep in sync with https://code.claude.com/docs/en/hooks — that page is the
# source of truth. Add an event here only after checking it there.
EVENTS = {
    "PreToolUse", "PostToolUse", "UserPromptSubmit", "Notification",
    "Stop", "SubagentStop", "SessionStart", "SessionEnd", "PreCompact",
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


def script_path_from(command):
    """Extract the script path a hook command runs, relative to the plugin root.

    Commands look like: "${CLAUDE_PLUGIN_ROOT}"/scripts/name.py [args]
    Returns None when there is nothing after the variable.
    """
    tail = command.split("}", 1)[-1] if "}" in command else ""
    tail = tail.strip().strip('"').strip()
    if not tail:
        return None
    return tail.split()[0].lstrip("/")


def check_scripts(base, cfg, label):
    """Check every command in a hooks.json: variable use, path safety, script sanity."""
    for event, groups in (cfg.get("hooks") or {}).items():
        if event not in EVENTS:
            err(f"{label}: unknown event '{event}'")
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

                if "CLAUDE_PLUGIN_ROOT" not in command:
                    err(f"{label}: command does not use ${{CLAUDE_PLUGIN_ROOT}}: {command}")
                if "/Users/" in command or "/home/" in command or "C:\\" in command:
                    err(f"{label}: command contains a personal path: {command}")
                if "timeout" not in hook:
                    warn(f"{label}: no timeout on the {event} command")

                rel = script_path_from(command)
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


def check_bundled_skills(base, label):
    """A hook may ship a skill that serves it; check it is well formed.

    Skipping the directory entirely would let a broken SKILL.md ship unnoticed,
    since Claude Code loads it from the same plugin as the hook.
    """
    skills_dir = os.path.join(base, "skills")
    if not os.path.isdir(skills_dir):
        return

    names = sorted(
        d for d in os.listdir(skills_dir)
        if os.path.isdir(os.path.join(skills_dir, d))
    )
    if not names:
        err(f"{label}: skills/ exists but holds no skill")
        return

    for skill in names:
        path = os.path.join(skills_dir, skill, "SKILL.md")
        if not os.path.isfile(path):
            err(f"{label}: skills/{skill}/SKILL.md is missing")
            continue

        with open(path, encoding="utf-8") as fh:
            text = fh.read()

        if not text.startswith("---"):
            err(f"{label}: skills/{skill}/SKILL.md has no YAML frontmatter")
            continue

        end = text.find("\n---", 3)
        if end == -1:
            err(f"{label}: skills/{skill}/SKILL.md frontmatter is not closed")
            continue

        front = text[3:end]
        fields = dict(
            re.match(r"^(\w+):\s*(.*)$", line).groups()
            for line in front.splitlines()
            if re.match(r"^(\w+):\s*(.*)$", line)
        )

        if fields.get("name") != skill:
            err(
                f"{label}: skills/{skill}/SKILL.md name "
                f"'{fields.get('name')}' != folder '{skill}'"
            )
        elif not fields.get("description"):
            err(f"{label}: skills/{skill}/SKILL.md has no description")
        else:
            ok(f"{label}: bundled skill {skill} is well formed")


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

# ------------------------------------------------------------------ _template

print("\nhooks/_template")
tpl = "hooks/_template"
if not os.path.isdir(tpl):
    err("the template is missing; contributors start from it")
else:
    # The template is not a real plugin: its name intentionally differs from the
    # folder and it is not in the marketplace. Everything else must still hold,
    # or people copy a broken starting point.
    manifest = load_json(os.path.join(tpl, ".claude-plugin", "plugin.json"), "_template")
    cfg = load_json(os.path.join(tpl, "hooks", "hooks.json"), "_template")
    if manifest is not None and cfg is not None:
        ok("manifest and hooks.json are valid JSON")
        check_scripts(tpl, cfg, "_template")
    if "_template" in listed:
        err("_template must not be listed in marketplace.json")

# ---------------------------------------------------------------------- hooks

on_disk = sorted(
    d for d in os.listdir("hooks")
    if os.path.isdir(os.path.join("hooks", d)) and not d.startswith("_")
)

for orphan in sorted(set(listed) - set(on_disk)):
    err(f"marketplace lists {orphan}, but hooks/{orphan} does not exist")

if not on_disk:
    print("\nno hooks yet")

for name in on_disk:
    print(f"\nhooks/{name}")
    base = os.path.join("hooks", name)

    if name not in listed:
        err(f"{name} is not listed in marketplace.json")

    if not os.path.isfile(os.path.join(base, "README.md")):
        err(f"{name}: missing README.md")

    manifest = load_json(os.path.join(base, ".claude-plugin", "plugin.json"), name)
    if manifest is not None:
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

    cfg = load_json(os.path.join(base, "hooks", "hooks.json"), name)
    if cfg is not None:
        if not (cfg.get("hooks") or {}):
            err(f"{name}: hooks.json registers no events")
        check_scripts(base, cfg, name)

    check_bundled_skills(base, name)

print()
if fail:
    print("validation failed", file=sys.stderr)
    sys.exit(1)
print("all checks passed" + (" (with warnings)" if warned else ""))
PY
