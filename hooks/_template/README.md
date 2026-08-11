# _template

Starting point for a new hook. Copy the folder, rename it, and replace everything below.

```bash
cp -r hooks/_template hooks/my-new-hook
```

The leading underscore keeps this folder out of `validate.sh` and out of the marketplace. Your copy
must not have one.

## Checklist

1. `.claude-plugin/plugin.json`: set `name` to the folder name, write a one-sentence description,
   start at version `0.1.0`.
2. `hooks/hooks.json`: pick the event and matcher. Reference the script as
   `"${CLAUDE_PLUGIN_ROOT}"/scripts/<name>`, quoted. Set a `timeout` if the work is not instant.
3. `scripts/`: write the script, `chmod +x`, keep the stdin/stdout contract in mind. The template
   script documents it at the top.
4. This README: replace it with what the hook does, which event and matcher it uses, what it blocks
   or changes, how to test it, how to disable it, and what it deliberately does not cover.
5. Register it in `.claude-plugin/marketplace.json` and in the table in the root `README.md`.
6. Run `./scripts/validate.sh`, then install it locally and trigger the event for real.

## Which event

| Event | Fires | Typical use |
| :--- | :--- | :--- |
| `PreToolUse` | Before a tool runs, can block it | Guardrails, policy checks |
| `PostToolUse` | After a tool succeeds | Formatting, linting, tests |
| `UserPromptSubmit` | When a prompt is submitted | Inject context, reject prompts |
| `Notification` | On a Claude Code notification | Desktop alerts, Slack pings |
| `Stop` | When the main agent finishes | Wrap-up work |
| `SubagentStop` | When a subagent finishes | Collect subagent output |
| `SessionStart` | On start or resume | Load branch state, env checks |
| `SessionEnd` | On session end | Cleanup, logging |
| `PreCompact` | Before context compaction | Persist state that would be lost |

If two events could work, prefer the later one. A `PostToolUse` hook that fixes formatting is less
disruptive than a `PreToolUse` hook that refuses badly formatted writes.
