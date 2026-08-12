#!/usr/bin/env bash
#
# ci-watch - report GitHub Actions results for the branch you are on.
#
# Contract: stdout is a message to Claude. So this prints on transitions only,
# never on a poll that found nothing new, and stays silent when there is nothing
# to say. Two rules decide what is worth an interruption:
#
#   - A run that FAILS is always reported. That is the whole point.
#   - A run that PASSES is reported only if we saw it running first. Green CI you
#     never knew was pending is not news; green CI after you pushed and waited is.
#
# It never reports the same state twice, so a run that stays red is announced
# once and then leaves you alone.
#
# Requires the `gh` CLI, authenticated. Without it the monitor says so once and
# then goes quiet for the session rather than repeating itself.
#
# Optional config at <plugin-data>/ci-watch.json. Monitors do not receive
# CLAUDE_PLUGIN_OPTION_* and cannot use ${user_config.*}, so a file the script
# owns is the documented way to configure one:
#
#     { "idleSeconds": 60, "activeSeconds": 20, "reportSuccess": true }

set -uo pipefail

DATA_DIR="${1:-}"
CONFIG="${DATA_DIR:+$DATA_DIR/ci-watch.json}"

IDLE_SECONDS=60
ACTIVE_SECONDS=20
REPORT_SUCCESS=1

say() { printf '%s\n' "$*"; }

# Stay alive without ever speaking again. A monitor that exits has silently
# stopped watching, which is worse than one that is quiet on purpose.
go_quiet() { exec tail -f /dev/null; }

load_config() {
  [[ -n "$CONFIG" && -f "$CONFIG" ]] || return 0
  command -v python3 > /dev/null 2>&1 || return 0
  local parsed
  parsed=$(python3 - "$CONFIG" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        cfg = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)
if not isinstance(cfg, dict):
    sys.exit(0)


def number(key, default, low, high):
    value = cfg.get(key, default)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


# Floor of 5s: ~720 calls an hour at the fastest setting, well inside the
# authenticated rate limit, and low enough to be useful on a very fast pipeline.
print(number("idleSeconds", 60, 5, 3600))
print(number("activeSeconds", 20, 5, 3600))
print(0 if cfg.get("reportSuccess") is False else 1)
PY
  )
  [[ -z "$parsed" ]] && return 0
  IDLE_SECONDS=$(sed -n 1p <<< "$parsed")
  ACTIVE_SECONDS=$(sed -n 2p <<< "$parsed")
  REPORT_SUCCESS=$(sed -n 3p <<< "$parsed")
}

load_config

# ---------------------------------------------------------------- preflight

if ! command -v gh > /dev/null 2>&1; then
  say "ci-watch: the gh CLI is not installed, so CI results will not be reported."
  go_quiet
fi

if ! git rev-parse --git-dir > /dev/null 2>&1; then
  # Not a repository. Nothing to watch, and nothing worth saying about it.
  go_quiet
fi

if ! gh repo view --json nameWithOwner > /dev/null 2>&1; then
  say "ci-watch: no GitHub repository here, or gh is not authenticated. CI results will not be reported."
  go_quiet
fi

# ------------------------------------------------------------------- watch

last_reported=""   # branch:run:status:conclusion that was last announced
watched_run=""     # a run id we have seen in progress, so its result is news

while :; do
  interval=$IDLE_SECONDS

  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [[ -z "$branch" || "$branch" == "HEAD" ]]; then
    sleep "$interval"
    continue
  fi

  # One call, tab separated. gh has jq built in, so no external dependency.
  run=$(gh run list --branch "$branch" --limit 1 \
          --json databaseId,status,conclusion,workflowName,url \
          --jq '.[0] | [.databaseId, .status, .conclusion, .workflowName, .url] | @tsv' \
        2>/dev/null)

  # No runs yet, or the call failed. A transient network error is not something
  # Claude needs to hear about.
  if [[ -z "$run" ]]; then
    sleep "$interval"
    continue
  fi

  IFS=$'\t' read -r run_id status conclusion workflow url <<< "$run"

  if [[ "$status" != "completed" ]]; then
    # Queued or running: remember it, poll faster, say nothing.
    watched_run="$run_id"
    sleep "$ACTIVE_SECONDS"
    continue
  fi

  key="$branch:$run_id:$status:$conclusion"
  if [[ "$key" == "$last_reported" ]]; then
    sleep "$interval"
    continue
  fi

  case "$conclusion" in
    success)
      # Only news if we watched it run.
      if [[ "$run_id" == "$watched_run" && "$REPORT_SUCCESS" == "1" ]]; then
        say "CI passed on ${branch} — ${workflow}"
        last_reported="$key"
      fi
      ;;
    failure|timed_out|startup_failure)
      say "CI ${conclusion} on ${branch} — ${workflow}. ${url}"
      last_reported="$key"
      ;;
    cancelled|skipped|neutral|action_required|"")
      # Not a result anyone needs interrupting for.
      last_reported="$key"
      ;;
    *)
      say "CI finished on ${branch} with '${conclusion}' — ${workflow}. ${url}"
      last_reported="$key"
      ;;
  esac

  sleep "$interval"
done
