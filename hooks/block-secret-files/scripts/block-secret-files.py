#!/usr/bin/env python3
"""PreToolUse hook: block file tools from touching secrets.

Reads the hook payload from stdin, looks at the path the tool is about to use, and
denies the call when that path looks like a secret. Exits 0 and prints a JSON
decision on stdout, which is the documented way to give Claude a reason it can act
on. Nothing else is ever printed to stdout, because extra output breaks parsing.

Fails open: if the payload is unreadable or the tool has no path, the call is
allowed. A guardrail that crashes should not take the session down with it.
"""

import fnmatch
import json
import os
import sys

# Matched against the file name and, for the slash patterns, against the path.
SECRET_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "*.kdbx",
    "credentials",
    "credentials.json",
    "service-account*.json",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".htpasswd",
]

# Path fragments that are secret regardless of file name.
SECRET_DIRS = [
    "/.ssh/",
    "/.gnupg/",
    "/.aws/",
    "/.docker/config.json",
    "/.kube/config",
]

# Allowed on purpose: examples and templates carry no real secrets.
ALLOW_PATTERNS = [
    "*.example",
    "*.example.*",
    "*.dist",
    "*.sample",
    "*.template",
    ".env.example",
    ".env.template",
    ".env.dist",
]

PATH_KEYS = ("file_path", "notebook_path", "path")


def allow():
    sys.exit(0)


def deny(path, reason):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Blocked by block-secret-files: {path} {reason}. "
                        "Ask the user to share the specific value you need, or work "
                        "with the .example variant instead."
                    ),
                }
            }
        )
    )
    sys.exit(0)


def is_secret(path):
    name = os.path.basename(path)
    normalised = path.replace("\\", "/")

    for pattern in ALLOW_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return None

    for fragment in SECRET_DIRS:
        if fragment in normalised:
            return f"is inside {fragment.strip('/')}"

    for pattern in SECRET_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return f"matches the secret pattern {pattern}"

    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        allow()

    for key in PATH_KEYS:
        path = tool_input.get(key)
        if isinstance(path, str) and path:
            reason = is_secret(path)
            if reason:
                deny(path, reason)

    allow()


if __name__ == "__main__":
    main()
