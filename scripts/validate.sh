#!/usr/bin/env bash
#
# validate.sh - structural checks for this repo. Run before opening a PR.
#
# Checks:
#   - marketplace.json is valid JSON and every plugin source resolves
#   - every hook has plugin.json and hooks/hooks.json, both valid JSON
#   - plugin.json name matches the folder name
#   - hook event names are recognised
#   - referenced scripts exist and are executable
#   - commands use "${CLAUDE_PLUGIN_ROOT}" instead of a relative or personal path
#   - every hook has a README.md
#
# It cannot tell you whether a hook is a good idea or safe. Read the diff for that.

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

fail=0
err() { echo "  FAIL: $*" >&2; fail=1; }
ok() { echo "  ok: $*"; }

echo "marketplace.json"
if python3 -m json.tool .claude-plugin/marketplace.json > /dev/null 2>&1; then
  ok "valid JSON"
else
  err "invalid JSON"
  exit 1
fi

python3 - <<'PY'
import json, os, sys

EVENTS = {
    "PreToolUse", "PostToolUse", "UserPromptSubmit", "Notification",
    "Stop", "SubagentStop", "SessionStart", "SessionEnd", "PreCompact",
}

fail = False


def err(msg):
    global fail
    print(f"  FAIL: {msg}", file=sys.stderr)
    fail = True


def ok(msg):
    print(f"  ok: {msg}")


mp = json.load(open(".claude-plugin/marketplace.json"))
listed = {p["name"]: p["source"] for p in mp.get("plugins", [])}

for name, source in listed.items():
    if not os.path.isdir(source):
        err(f"{name}: source {source} does not exist")

on_disk = sorted(
    d for d in os.listdir("hooks")
    if os.path.isdir(os.path.join("hooks", d)) and not d.startswith("_")
)

for name in on_disk:
    print(f"\nhooks/{name}")
    base = os.path.join("hooks", name)

    if name not in listed:
        err(f"{name} is not listed in marketplace.json")

    manifest_path = os.path.join(base, ".claude-plugin", "plugin.json")
    hooks_path = os.path.join(base, "hooks", "hooks.json")

    for path in (manifest_path, hooks_path):
        if not os.path.isfile(path):
            err(f"missing {path}")

    if not os.path.isfile(os.path.join(base, "README.md")):
        err(f"{name}: missing README.md")

    if os.path.isfile(manifest_path):
        try:
            manifest = json.load(open(manifest_path))
            if manifest.get("name") != name:
                err(f"plugin.json name '{manifest.get('name')}' != folder '{name}'")
            else:
                ok("plugin.json name matches folder")
        except json.JSONDecodeError as e:
            err(f"plugin.json invalid JSON: {e}")

    if not os.path.isfile(hooks_path):
        continue

    try:
        cfg = json.load(open(hooks_path))
    except json.JSONDecodeError as e:
        err(f"hooks.json invalid JSON: {e}")
        continue

    for event, groups in (cfg.get("hooks") or {}).items():
        if event not in EVENTS:
            err(f"unknown event '{event}'")
        else:
            ok(f"event {event}")

        for group in groups:
            for hook in group.get("hooks", []):
                if hook.get("type") != "command":
                    continue
                command = hook.get("command", "")

                if "CLAUDE_PLUGIN_ROOT" not in command:
                    err(f"command does not use ${{CLAUDE_PLUGIN_ROOT}}: {command}")
                if "/Users/" in command or "/home/" in command:
                    err(f"command contains a personal path: {command}")

                tail = command.split("}")[-1].strip().strip('"').lstrip("/")
                script = os.path.join(base, tail.split()[0]) if tail else ""
                if script and os.path.isfile(script):
                    if os.access(script, os.X_OK):
                        ok(f"script {tail} exists and is executable")
                    else:
                        err(f"script {tail} is not executable (chmod +x)")
                elif script:
                    err(f"script {tail} not found at {script}")

print()
sys.exit(1 if fail else 0)
PY

status=$?
if [[ $status -ne 0 || $fail -ne 0 ]]; then
  echo "validation failed" >&2
  exit 1
fi

echo "all checks passed"
