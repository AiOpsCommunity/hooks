# AiOps Community hooks and monitors

Things that run automatically in your Claude Code session, packaged as plugins so they can be
installed with one command and updated later.

Two kinds live here, and they are mirror images of each other. A **hook** reacts to something Claude
does: it fires on a lifecycle event and can block, format or record. A **monitor** reacts to
something the world does: it runs in the background for the whole session and every line it prints
reaches Claude as a notification, so Claude learns about a failing build or a log entry without
anyone asking it to look.

> **Claude Code only.** Unlike skills, there is no file to upload in claude.ai. Both are
> configuration that Claude Code executes, so the only shareable form is a plugin containing a
> `hooks/hooks.json` or a `monitors/monitors.json`. That is what every entry here is.

They share a repository because they share a trust model: both run unsandboxed, automatically, with
your credentials. That is what [CONTRIBUTING.md](CONTRIBUTING.md) is written around. Skills and
agents, which only influence what Claude says, live in
[AiOpsCommunity/skills](https://github.com/AiOpsCommunity/skills).

## Hooks

_No hooks yet — yours can be the first. See [CONTRIBUTING.md](CONTRIBUTING.md)._

| Hook | Event | Description |
| :--- | :---- | :---------- |

## Monitors

| Monitor | Watches | Description |
| :--- | :---- | :---------- |
| [`log-watch`](monitors/log-watch/) | Log files | Reports only the lines matching patterns you configure, rate limited so a noisy log cannot flood the session. |

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
├── hooks/
│   ├── _template/                # copy this to start a new hook
│   └── <hook-name>/
│       ├── .claude-plugin/
│       │   └── plugin.json       # manifest, metadata only
│       ├── hooks/
│       │   └── hooks.json        # the hook config (same shape as settings.json)
│       ├── scripts/
│       │   └── <script>          # what the hook actually runs
│       └── README.md             # what it does, why, how to test, how to disable
└── monitors/
    ├── _template/                # copy this to start a new monitor
    └── <monitor-name>/
        ├── .claude-plugin/
        │   └── plugin.json
        ├── monitors/
        │   └── monitors.json     # array of monitor entries
        ├── scripts/
        │   └── <script>          # the long-running command
        └── README.md
```

The nesting looks odd at first: `hooks/<hook-name>/hooks/hooks.json`. The outer directory is this
repo's catalog. The inner one is where Claude Code looks inside a plugin — `hooks/hooks.json` and
`monitors/monitors.json` are both defaults it discovers on its own. Manifests live in
`.claude-plugin/`, everything functional lives at the plugin root.

## Add a new hook

1. Copy the template and rename it (kebab-case, this becomes the plugin name):

   ```bash
   cp -r hooks/_template hooks/my-new-hook
   ```

2. Fill in `.claude-plugin/plugin.json`, `hooks/hooks.json`, the script, and the README.
3. Add a plugin entry to [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) and a
   row to the table above.
4. Run `./scripts/validate.sh` and test locally (see CONTRIBUTING.md).

## Add a new monitor

Same shape, different directory and config file:

```bash
cp -r monitors/_template monitors/my-new-monitor
```

Fill in `.claude-plugin/plugin.json` and `monitors/monitors.json`, write the script, register it in
`marketplace.json` and the Monitors table, and validate. The template README explains the contract:
**stdout is a message to Claude**, so print only what deserves to interrupt.

Monitors run only in interactive CLI sessions, run unsandboxed at the same trust level as hooks, and
are an experimental component whose schema may still change. Note that `${user_config.*}` is not
substituted into a monitor command and monitor processes do not receive `CLAUDE_PLUGIN_OPTION_<KEY>`,
so a monitor that needs configuration reads it from a file the script owns.

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
