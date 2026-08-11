#!/usr/bin/env bash
#
# pr-policy.sh - checks the shape of a pull request, not the content of a hook.
#
#   - one hook per pull request
#   - a new hook is registered in marketplace.json and listed in the README
#   - the template is not silently modified alongside a hook
#
# Usage: ./scripts/pr-policy.sh [base-ref]     (default: origin/main)
#
# Run it locally before pushing. CI runs the same script against the PR base.

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root" || exit 1

base="${1:-origin/main}"

if ! git rev-parse --verify --quiet "$base" > /dev/null; then
  echo "FAIL: base ref '$base' not found. Fetch it first, or pass another ref." >&2
  exit 1
fi

merge_base="$(git merge-base "$base" HEAD)"
changed="$(git diff --name-only "$merge_base" HEAD)"

if [[ -z "$changed" ]]; then
  echo "no changes against $base"
  exit 0
fi

echo "changed files vs $base:"
echo "$changed" | sed 's/^/  /'
echo

CHANGED="$changed" BASE="$merge_base" python3 - <<'PY'
import os
import subprocess
import sys

changed = [line for line in os.environ["CHANGED"].splitlines() if line.strip()]
base = os.environ["BASE"]

fail = False


def err(msg):
    global fail
    print(f"FAIL: {msg}", file=sys.stderr)
    fail = True


def ok(msg):
    print(f"ok: {msg}")


def existed_at_base(path):
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{base}:{path}"],
        capture_output=True,
    )
    return result.returncode == 0


touched = []
for path in changed:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "hooks" and parts[1] not in touched:
        touched.append(parts[1])

hooks = [name for name in touched if not name.startswith("_")]

if "_template" in touched and hooks:
    err(
        "this PR changes both the template and a hook. Split them: a template "
        "change affects everyone who starts a new hook and deserves its own review."
    )

if not hooks:
    ok("no hook directories touched (infrastructure or docs change)")
elif len(hooks) > 1:
    err(
        "one hook per pull request, this one touches "
        + ", ".join(sorted(hooks))
        + ". Split it: a reviewer reading shell that runs automatically should "
        "have one thing in front of them."
    )
else:
    name = hooks[0]
    ok(f"exactly one hook touched: {name}")

    is_new = not existed_at_base(f"hooks/{name}/.claude-plugin/plugin.json")
    if is_new:
        print(f"note: {name} is new, so it must be registered")
        if ".claude-plugin/marketplace.json" not in changed:
            err(
                f"{name} is new but .claude-plugin/marketplace.json is unchanged. "
                "Without an entry there, nobody can install it."
            )
        else:
            ok("marketplace.json updated")

        if "README.md" not in changed:
            err(
                f"{name} is new but README.md is unchanged. Add a row to the "
                "Hooks table so it is discoverable."
            )
        else:
            ok("README.md updated")

        # The row has to actually mention the hook, not just be a whitespace edit.
        if "README.md" in changed:
            with open("README.md") as fh:
                if name not in fh.read():
                    err(f"README.md does not mention {name}")
                else:
                    ok(f"README.md mentions {name}")
    else:
        ok(f"{name} already existed, treating this as an edit")

sys.exit(1 if fail else 0)
PY

status=$?
echo
if [[ $status -ne 0 ]]; then
  echo "pr-policy failed" >&2
  exit 1
fi
echo "pr-policy passed"
