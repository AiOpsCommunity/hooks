#!/usr/bin/env bash
#
# Template monitor. Copy, rename, and replace the body.
#
# Contract:
# - This runs as a long-lived background process for the whole session.
# - Every line printed to stdout is delivered to Claude as a notification.
#   Print a line only when something happened that Claude should act on.
# - Exit codes are not a signalling channel here. Silence is success.
# - Keep the output short and specific. "PHP Fatal error in OrderConverter.php
#   line 88" is useful. Fifty lines of stack trace on every request is not.
# - The process is killed when the session ends. Clean up on EXIT if you must.

set -uo pipefail

# The session working directory is where this starts, so relative paths refer
# to the user's project. Use "${CLAUDE_PROJECT_DIR}" if you need it explicitly.
LOG="${CLAUDE_PROJECT_DIR:-.}/var/log/dev.log"

if [[ ! -f "$LOG" ]]; then
  # Say nothing and stay alive: the file may appear later.
  exec tail -f /dev/null
fi

# Only forward lines worth interrupting Claude for.
tail -Fn0 "$LOG" 2>/dev/null | while IFS= read -r line; do
  case "$line" in
    *CRITICAL*|*"Fatal error"*|*Exception*)
      printf '%s\n' "$line"
      ;;
  esac
done
