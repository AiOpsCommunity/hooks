# Contributing

Each hook is a plugin folder under `hooks/`. See [README.md](README.md) for the layout and install
instructions.

Hooks deserve more scrutiny than skills. A skill is text that Claude may or may not act on. A hook
is shell that runs automatically, with your credentials, without confirmation, on every matching
event. Review PRs here with that in mind, and expect the same of your own.

## Rules

- **One hook per pull request.**
- Folder name is **kebab-case** and becomes the plugin name. Keep `name` in `plugin.json` equal to
  the folder name.
- Every hook ships a `README.md` covering: what it does, which event and matcher, what it blocks or
  changes, how to test it, and how to disable it.
- Reference bundled scripts with **exec form**: put the interpreter in `command` and the script in
  `args`, using `${CLAUDE_PLUGIN_ROOT}`. Never a relative path, never a path on your own machine.

  ```json
  { "type": "command", "command": "python3",
    "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/my-hook.py"], "timeout": 10 }
  ```

  Exec form spawns the script directly instead of handing a string to `sh -c`, so quoting, spaces
  and `$` in a path stop being your problem. Shell form still works and is the right choice when you
  genuinely need a pipe or `&&`, but then every placeholder must be double-quoted.
- Configuration that decides **what a hook is allowed to do** belongs in `userConfig` in
  `plugin.json`, not in a file inside the project. Claude Code prompts for those values when the
  plugin is enabled, stores them in user settings, and passes them to the hook as
  `CLAUDE_PLUGIN_OPTION_<KEY>`. A config file in the repository can be supplied by any repository you
  clone, which makes it useless as a trust boundary — Claude Code ignores project-level
  `pluginConfigs` for exactly this reason.
- Scripts must be executable (`chmod +x`) and start with a shebang.
- Exit codes: `0` is success, `2` blocks the action and sends stderr back to Claude, anything else
  is a non-blocking error shown to the user. If you print JSON on stdout, exit `0` and print
  **nothing else**, or parsing breaks.
- Keep it fast. Hooks run inline on every matching event, so a slow hook is felt on every tool call.
  Set a `timeout` when the work is not instant.
- Prefer `python3` or POSIX shell over tools that may not be installed. If you need `jq`, say so in
  the README and fail with a clear message when it is missing.

## Not accepted

- Network calls that are not the entire point of the hook, and never without saying so in the README
  and making them opt-in.
- Reading `.env`, keychains, SSH keys, tokens, or anything else the hook does not strictly need.
- Writing outside the project directory, or anything destructive without an explicit opt-in.
- Hooks that silently modify Claude's input or output in ways the README does not describe.
- Obfuscated code, `curl | sh`, or anything downloaded at runtime.

## Before opening a PR

```bash
./scripts/validate.sh                        # repo structure, registration, script permissions
./scripts/pr-policy.sh                       # one hook per PR, and the hook is registered
./scripts/review-flags.sh                    # lines a reviewer should read closely (never fails)
claude plugin validate ./hooks/<name> --strict   # the official manifest schema check
```

The last one is Claude Code's own validator and catches things ours cannot: a misspelled manifest
field, a value of the wrong type, a field left over from another tool's manifest. `--strict` makes
warnings fail, which is what you want before publishing.

CI runs the same three scripts on every pull request, so a green run here is a green run there.
`structure`, `lint` and `pr-policy` must pass before a PR can merge. `review-flags` is advisory: it
prints a table of lines worth a second look and always passes, because every pattern it knows has
legitimate uses. If it flags your hook, explain why in the PR rather than leaving the reviewer to
work it out.

Then test for real:

```bash
/plugin marketplace add ./       # from the repo root
/plugin install my-new-hook@aiops-hooks
/hooks                           # confirm it is registered on the right event
```

Trigger the event and confirm the hook fires, then confirm it does **not** fire where it should not.
For a blocking hook, test both paths: the case it blocks and a normal case it must leave alone. Run
`claude --debug` to see hook execution and JSON parse errors.

Note in the PR which of these you ran and what the output was.
