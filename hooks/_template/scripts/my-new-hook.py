#!/usr/bin/env python3
"""Template hook script. Copy, rename, and replace the body.

Contract:
- The hook payload arrives as JSON on stdin. Common fields: session_id, cwd,
  hook_event_name, tool_name, tool_input.
- Exit 0 for success. Exit 2 to block the action, with the reason on stderr.
  Any other exit code is a non-blocking error shown to the user.
- If you print JSON on stdout, exit 0 and print nothing else. Extra output
  breaks parsing.
- Fail open unless the hook exists specifically to block. A guardrail that
  crashes should not take the session down with it.
"""

import json
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")

    if not file_path:
        sys.exit(0)

    # Do the work here. Keep it fast: this runs on every matching event.

    # To block, uncomment:
    # print(f"Refusing to touch {file_path}: <reason>", file=sys.stderr)
    # sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
