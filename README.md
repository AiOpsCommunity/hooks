# AiOps Community hooks

A collection of [Claude Code hooks](https://code.claude.com/docs/en/hooks), packaged as plugins so
they can be installed with one command and updated later.

> **Hooks are Claude Code only.** Unlike skills, there is no `.hook` file and no upload in
> claude.ai. A hook is shell configuration that Claude Code runs at a lifecycle event, so the only
> shareable form is a plugin containing a `hooks/hooks.json`. That is what every entry in this repo
> is.

## Hooks

| Hook | Event | Description |
| :--- | :---- | :---------- |
| [`block-secret-files`](hooks/block-secret-files/) | `PreToolUse` | Blocks reads and writes of secret files (`.env`, private keys, credential stores) before the tool runs. |
| [`claude-md-maintainer`](hooks/claude-md-maintainer/) | `Stop` | Collects candidate CLAUDE.md lines into a local, git-excluded inbox; a bundled skill verifies them, prunes stale lines and enforces a size budget. |
| [`git-guardrails`](hooks/git-guardrails/) | `PreToolUse` | Blocks irreversible git operations: force pushes to protected branches, hard resets over uncommitted work, protected branch deletion, untracked file wipes and history rewrites. |
| [`project-checks`](hooks/project-checks/) | `PostToolUse` | Runs the formatter or linter a project already defines on the file just edited, returning failures so they are fixed in the same turn. Runs only in directories you mark as trusted. |

## Install

```text
/plugin marketplace add AiOpsCommunity/hooks
/plugin install <hook-name>@aiops-hooks
/reload-plugins
```

Verify with `/hooks`, which lists every registered hook and where it came from. Update later with
`/plugin marketplace update aiops-hooks`.

### Without the marketplace

Copy the scripts somewhere stable and register the hook yourself in `~/.claude/settings.json`
(personal) or `.claude/settings.json` (one project). Each hook's own README shows the settings
block, since `${CLAUDE_PLUGIN_ROOT}` does not exist outside a plugin and has to be replaced with a
real path.

## Repo layout

```
.
├── README.md
├── CONTRIBUTING.md
├── .claude-plugin/
│   └── marketplace.json          # plugin catalog for /plugin install
├── .github/
│   └── workflows/
│       └── pr-checks.yml         # runs the scripts below on every PR
├── scripts/
│   ├── validate.sh               # structure: JSON, events, paths, permissions
│   ├── pr-policy.sh              # one hook per PR, registered properly
│   └── review-flags.sh           # advisory: lines a reviewer should read
└── hooks/
    ├── _template/                # copy this to start a new hook
    └── <hook-name>/
        ├── .claude-plugin/
        │   └── plugin.json       # manifest, metadata only
        ├── hooks/
        │   └── hooks.json        # the hook config (same shape as settings.json)
        ├── scripts/
        │   └── <script>          # what the hook actually runs
        ├── skills/               # optional, only when it serves the hook
        │   └── <name>/SKILL.md
        └── README.md             # what it does, why, how to test, how to disable
```

The nesting looks odd at first: `hooks/<hook-name>/hooks/hooks.json`. The outer `hooks/` is this
repo's catalog directory. The inner one is required by Claude Code, which looks for `hooks/hooks.json`
at the root of a plugin. Manifests live in `.claude-plugin/`, everything functional lives at the
plugin root.

## Add a new hook

1. Copy the template and rename it (kebab-case, this becomes the plugin name):

   ```bash
   cp -r hooks/_template hooks/my-new-hook
   ```

2. Fill in `.claude-plugin/plugin.json`, `hooks/hooks.json`, the script, and the README.
3. Add a plugin entry to [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) and a
   row to the table above.
4. Run `./scripts/validate.sh` and test locally (see CONTRIBUTING.md).

## Events you can hook into

| Event | Fires | Typical use |
| :--- | :--- | :--- |
| `PreToolUse` | Before a tool runs, can block it | Guardrails, policy checks |
| `PostToolUse` | After a tool succeeds | Formatting, linting, tests |
| `UserPromptSubmit` | When a prompt is submitted | Inject context, reject prompts |
| `Notification` | On a Claude Code notification | Desktop alerts, Slack pings |
| `Stop` | When the main agent finishes | Wrap-up work, changelog updates |
| `SubagentStop` | When a subagent finishes | Collect subagent output |
| `SessionStart` | On start or resume | Load branch state, env checks |
| `SessionEnd` | On session end | Cleanup, logging |
| `PreCompact` | Before context compaction | Persist state that would be lost |

That table is the common set, not the whole list — Claude Code ships around thirty events, including
`PostToolUseFailure`, `PermissionRequest`, `FileChanged`, `SubagentStart` and `TaskCompleted`.
`validate.sh` only *warns* about an event it does not recognise, so a hook on a newer event is never
blocked by this repo being a release behind.

`matcher` filters within an event. For tool events it matches the tool name and accepts regex
alternation (`Write|Edit`); MCP tools are matched as `mcp__<server>__<tool>`. Leave it out to match
everything.

## Things worth knowing

| Feature | What it gives you |
| :--- | :--- |
| `if: "Bash(git *)"` | Narrows a tool hook further than `matcher` can, using permission-rule syntax. Strips `NAME=value` prefixes and fails open when it cannot parse. |
| `args` (exec form) | Spawns the script directly instead of through `sh -c`. No quoting traps. See CONTRIBUTING.md. |
| `userConfig` | Values Claude Code prompts for at enable time, stored in *user* settings and passed to the hook as `CLAUDE_PLUGIN_OPTION_<KEY>`. The right place for anything that decides what a hook may do. |
| `defaultEnabled: false` | Ships the plugin installed but switched off, for hooks that add cost or scope. |
| `async` / `asyncRewake` | Runs a slow hook in the background; `asyncRewake` wakes Claude on exit 2 with the output. |
| `${CLAUDE_PLUGIN_DATA}` | A per-plugin directory that survives updates, unlike `${CLAUDE_PLUGIN_ROOT}`. |

Check [the hooks reference](https://code.claude.com/docs/en/hooks) and the
[plugins reference](https://code.claude.com/docs/en/plugins-reference) before relying on details
here; those pages are the source of truth and this is a summary.
