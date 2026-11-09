#!/usr/bin/env bash
#
# selftest.sh - runs the recorded cases of every hook and monitor script that has them.
#
# validate.sh checks that a hook is well formed. This checks that it still makes
# the decisions it is meant to make. A script opts in by accepting --selftest:
# it runs its own table of cases and exits non-zero when one of them fails.
#
# Fails when a selftest fails. A script without one is listed, never failed,
# because not every script decides something worth a table.
#
# Usage: ./scripts/selftest.sh

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root" || exit 1

status=0
passed=0
without=()

while IFS= read -r script; do
  if ! grep -q -- '--selftest' "$script"; then
    without+=("$script")
    continue
  fi
  echo "== $script"
  if "./$script" --selftest; then
    passed=$((passed + 1))
  else
    echo "FAIL: $script --selftest" >&2
    status=1
  fi
  echo
done < <(find hooks monitors -path '*/scripts/*' -type f \
           -not -path '*/_template/*' -not -path '*/__pycache__/*' | sort)

if [[ ${#without[@]} -gt 0 ]]; then
  echo "no selftest:"
  printf '  %s\n' "${without[@]}"
  echo
fi

if [[ $status -ne 0 ]]; then
  echo "selftest failed" >&2
  exit 1
fi
echo "selftest passed ($passed script(s))"
