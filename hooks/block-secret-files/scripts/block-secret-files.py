#!/usr/bin/env python3
"""PreToolUse hook: block file tools from touching secrets.

Reads the hook payload from stdin, looks at the path the tool is about to use, and
denies the call when that path looks like a secret. Exits 0 and prints a JSON
decision on stdout, which is the documented way to give Claude a reason it can act
on. Nothing else is ever printed to stdout, because extra output breaks parsing.

Fails open: if the payload is unreadable or the tool has no path, the call is
allowed. A guardrail that crashes should not take the session down with it.

Run with --selftest to check every recorded path against what it should get.
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


def find_secret(tool_input):
    """The first (path, reason) in the tool input that is a secret, or None."""
    if not isinstance(tool_input, dict):
        return None
    for key in PATH_KEYS:
        path = tool_input.get(key)
        if isinstance(path, str) and path:
            reason = is_secret(path)
            if reason:
                return path, reason
    return None


# (tool input, expected). Each row that is allowed sits next to the secret it
# could be mistaken for.
SELFTEST = [
    ({"file_path": ".env"}, "deny"),
    ({"file_path": "/repo/.env"}, "deny"),
    ({"file_path": "/repo/.env.local"}, "deny"),
    ({"file_path": "/repo/config/.env.production"}, "deny"),
    ({"file_path": "/repo/certs/server.pem"}, "deny"),
    ({"file_path": "/repo/tls.key"}, "deny"),
    ({"file_path": "/home/me/.ssh/id_ed25519"}, "deny"),
    ({"file_path": "/home/me/.ssh/config"}, "deny"),
    ({"file_path": "/home/me/.aws/credentials"}, "deny"),
    ({"file_path": "/home/me/.kube/config"}, "deny"),
    ({"file_path": "/home/me/.docker/config.json"}, "deny"),
    ({"file_path": "/repo/service-account-prod.json"}, "deny"),
    ({"file_path": "/home/me/.npmrc"}, "deny"),
    ({"file_path": "/home/me/vault.kdbx"}, "deny"),
    ({"file_path": "C:\\Users\\me\\.ssh\\id_rsa"}, "deny"),
    ({"notebook_path": "/repo/.env"}, "deny"),
    ({"path": "/home/me/.gnupg/pubring.kbx"}, "deny"),
    ({"file_path": "/repo/README.md", "path": "/repo/.env"}, "deny"),
    ({"file_path": "/repo/.env.example"}, "allow"),
    ({"file_path": "/repo/.env.template"}, "allow"),
    ({"file_path": "/repo/.env.dist"}, "allow"),
    ({"file_path": "/repo/settings.example.json"}, "allow"),
    ({"file_path": "/repo/src/env.ts"}, "allow"),
    ({"file_path": "/repo/src/environment.py"}, "allow"),
    ({"file_path": "/repo/docs/credentials.md"}, "allow"),
    ({"file_path": "/repo/src/keys.py"}, "allow"),
    ({"file_path": "/repo/monkey.ts"}, "allow"),
    ({"file_path": "/repo/.ssh-notes.md"}, "allow"),
    ({"file_path": ""}, "allow"),
    ({}, "allow"),
    ("not a dict", "allow"),
]


def selftest():
    failures = 0
    for tool_input, expected in SELFTEST:
        got = "deny" if find_secret(tool_input) else "allow"
        if got != expected:
            failures += 1
            print(f"FAIL {tool_input!r}: expected {expected}, got {got}")
    print(f"{len(SELFTEST) - failures}/{len(SELFTEST)} cases pass")
    return 1 if failures else 0


def main():
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()

    found = find_secret(payload.get("tool_input") or {})
    if found:
        deny(*found)

    allow()


if __name__ == "__main__":
    main()
