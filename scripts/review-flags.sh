#!/usr/bin/env bash
#
# review-flags.sh - points a reviewer at the lines worth reading closely.
#
# This is deliberately ADVISORY. It always exits 0 and never blocks a merge.
#
# Why not blocking: every pattern here has legitimate uses. block-secret-files
# mentions .ssh and .aws because those are the paths it protects. A hook that
# formats code has every right to call a subprocess. A scanner that fails the
# build on those would train people to route around it, which is worse than
# having no scanner. The real control on this repo is a human reading the diff;
# this script only makes sure they know where to look.
#
# Usage: ./scripts/review-flags.sh [base-ref]
#        With a base ref, only scans files changed against it. Without, scans
#        every hook script in the repo.

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root" || exit 1

base="${1:-}"

if [[ -n "$base" ]] && git rev-parse --verify --quiet "$base" > /dev/null; then
  merge_base="$(git merge-base "$base" HEAD)"
  files="$(git diff --name-only "$merge_base" HEAD -- 'hooks/*' 'monitors/*' | grep -E '\.(py|sh|js|ts|rb|pl)$')"
  scope="changed against $base"
else
  files="$(git ls-files 'hooks/*' 'monitors/*' | grep -E '\.(py|sh|js|ts|rb|pl)$')"
  scope="all hook and monitor scripts"
fi

FILES="$files" SCOPE="$scope" python3 - <<'PY'
import os
import re
import sys

# pattern -> why a reviewer should care
CHECKS = [
    (r"\b(curl|wget)\b", "network call from a shell command"),
    (r"\b(requests|urllib|httpx|http\.client|socket)\b", "network library import"),
    (r"\bnc\b|\bnetcat\b", "raw network tooling"),
    (r"\|\s*(sh|bash)\b", "piping something into a shell"),
    (r"\b(eval|exec)\s*\(", "dynamic code execution"),
    (r"\bos\.system\b|\bsubprocess\b|\bpopen\b", "spawning a process"),
    (r"\bbase64\b|\bcodecs\.decode\b|\bfromhex\b", "encoded payload, check what it decodes to"),
    (r"\.ssh/|\.gnupg/|\.aws/|id_rsa|keychain|Keychain", "credential path"),
    (r"\.env\b|SECRET|TOKEN|PASSWORD|API_KEY", "secret-shaped identifier"),
    (r"\brm\s+-rf\b|shutil\.rmtree|os\.remove|os\.unlink", "deletes files"),
    (r"\bopen\s*\([^)]*['\"][wa]", "writes a file"),
    (r"\bpip\s+install\b|\bnpm\s+i(nstall)?\b|\bgem\s+install\b", "installs something at runtime"),
    (r"os\.environ|getenv|\$HOME|~/", "reads the environment or home directory"),
]

files = [f for f in os.environ["FILES"].splitlines() if f.strip()]
scope = os.environ["SCOPE"]

# Grouped per (file, reason). A hook that lists secret patterns hits the same
# check on twenty consecutive lines; twenty rows saying the same thing is noise,
# and noise is how a reviewer learns to scroll past this table.
groups = {}
for path in files:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        continue

    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip pure comment lines: a comment cannot execute.
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        for pattern, why in CHECKS:
            if re.search(pattern, line):
                entry = groups.setdefault((path, why), {"count": 0, "first": (number, stripped)})
                entry["count"] += 1
                break

rows = [
    (path, why, data["count"], data["first"][0], data["first"][1][:90])
    for (path, why), data in sorted(groups.items())
]

out = []
out.append("## Review flags\n")
out.append(f"Scope: {scope} ({len(files)} file(s)).\n")

if not files:
    out.append("No hook or monitor scripts in scope.\n")
elif not rows:
    out.append("Nothing flagged. Still read the diff — this script only knows patterns.\n")
else:
    total = sum(row[2] for row in rows)
    out.append(
        f"{total} line(s) across {len(rows)} file/reason pair(s) worth a closer "
        "look. **These are not failures.** Every pattern below has legitimate "
        "uses; the point is that a human decides, not a regex.\n"
    )
    out.append("| File | Why | Hits | First at | Example |")
    out.append("| :--- | :-- | ---: | -------: | :------ |")
    for path, why, count, number, code in rows[:60]:
        code = code.replace("|", "\\|").replace("`", "'")
        out.append(f"| `{path}` | {why} | {count} | {number} | `{code}` |")
    if len(rows) > 60:
        out.append(f"\n_{len(rows) - 60} more pair(s) not shown._")
    out.append("")

out.append(
    "\nReviewer checklist for anything flagged: does the hook's README say it "
    "does this? Is it needed for the hook's stated job? Would you run it on "
    "your own machine, on every matching event, without being asked?\n"
)

text = "\n".join(out)
print(text)

summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as fh:
        fh.write(text)
PY

# Advisory by design: never fails the build.
exit 0
