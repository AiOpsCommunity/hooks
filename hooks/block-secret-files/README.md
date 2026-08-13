# block-secret-files

Blocks Claude Code from reading or writing files that look like secrets, before the tool runs.

**Event:** `PreToolUse`
**Matcher:** `Read|Edit|Write|NotebookEdit`
**Script:** `scripts/block-secret-files.py` (Python 3, no dependencies)

## What it does

Reads the path the tool is about to touch and denies the call when it matches a secret pattern.
Claude receives the reason and can act on it, usually by asking you for the one value it needs
instead of slurping the whole file.

Blocked: `.env` and variants, `*.pem`, `*.key`, `*.p12`, `*.pfx`, keystores, `id_rsa` and friends,
`*.kdbx`, `credentials`, `service-account*.json`, `.npmrc`, `.pypirc`, `.netrc`, `.htpasswd`, and
anything inside `.ssh/`, `.gnupg/`, `.aws/`, plus `.docker/config.json` and `.kube/config`.

Explicitly allowed: `*.example`, `*.sample`, `*.template`, `*.dist` and the `.env.example` family.
Those are the files Claude should be reading anyway.

## What it does not do

- It does not stop `Bash`. `cat .env` still works, because blocking shell commands reliably needs
  command parsing rather than path matching. Add a `Bash` matcher yourself if you want that, and
  expect false positives.
- It does not scan file contents. A secret pasted into `config.php` goes through.
- It fails open. An unreadable payload or a tool without a path is allowed through, on the grounds
  that a broken guardrail should not break your session.

Treat it as a seatbelt, not a vault.

## Install

```text
/plugin marketplace add AiOpsCommunity/hooks
/plugin install block-secret-files@aiops-hooks
/reload-plugins
```

Without the marketplace, copy `scripts/block-secret-files.py` somewhere stable, `chmod +x` it, and
add this to `~/.claude/settings.json` with the real path:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Edit|Write|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/block-secret-files.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

## Test it

Directly, without Claude Code:

```bash
echo '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"/app/.env"}}' \
  | ./scripts/block-secret-files.py
# -> {"hookSpecificOutput": {... "permissionDecision": "deny" ...}}

echo '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"/app/.env.example"}}' \
  | ./scripts/block-secret-files.py
# -> no output, exit 0
```

In a session: install it, run `/hooks` to confirm it is registered, then ask Claude to read `.env`
and confirm it is refused. Then ask it to read `.env.example` and confirm that still works.

## Disable

`/plugin uninstall block-secret-files@aiops-hooks`, or remove the block from `settings.json` if you
installed it manually. For a one-off exception, rename the file or point Claude at the value you
want it to have.

## Tuning

Edit `SECRET_PATTERNS`, `SECRET_DIRS` and `ALLOW_PATTERNS` at the top of the script. Patterns are
`fnmatch` globs matched against the file name, except `SECRET_DIRS` which matches path fragments.
