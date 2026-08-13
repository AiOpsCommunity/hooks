# _template

Starting point for a new monitor. Copy the folder, rename it, and replace everything below.

```bash
cp -r monitors/_template monitors/my-new-monitor
```

The leading underscore keeps this folder out of `validate.sh` and out of the marketplace. Your copy must not have one.

## What a monitor is

A shell command that runs for the whole session, in the background. Every line it prints to stdout is delivered to Claude as a notification. That is the entire interface: **stdout is a message to Claude**.

It is the mirror image of a hook. A hook reacts to something Claude does; a monitor reacts to something the world does, and tells Claude about it. Nothing has to ask for it — the watch is already running.

## Checklist

1. `.claude-plugin/plugin.json`: set `name` to the folder name, write a one-sentence description, start at version `0.1.0`.
2. `monitors/monitors.json`: give each monitor a `name`, `command` and `description`. Reference a bundled script as `"${CLAUDE_PLUGIN_ROOT}"/scripts/<name>`, quoted. Add `"when": "on-skill-invoke:<skill>"` if it should only start once a particular skill in your plugin runs.
3. `scripts/`: write the script, `chmod +x`, and read the contract at the top of the template script.
4. This README: replace it with what the monitor watches, what it prints, how to test it, and how to turn it off.
5. Register it in `.claude-plugin/marketplace.json` and the Monitors table in the repo README.
6. Run `./scripts/validate.sh` and `claude plugin validate ./monitors/my-new-monitor --strict`.

## The one rule that matters

**Print only what deserves to interrupt.** Every line costs context and pulls Claude's attention. A monitor that forwards an entire log turns a session into noise, and the first thing anyone will do is uninstall it. Filter hard, in the script, before printing.

Ask of every line: would I tap someone on the shoulder for this?

## Constraints worth knowing before you start

- Monitors run only in **interactive CLI sessions**. Headless and cloud runs skip them.
- They run **unsandboxed**, at the same trust level as hooks. Same review bar.
- `${user_config.*}` is **not** substituted into a monitor command, and monitor processes do **not** receive `CLAUDE_PLUGIN_OPTION_<KEY>`. If your monitor needs configuration, have the script read a file it owns.
- Disabling a plugin mid-session does **not** stop a monitor that is already running. It stops when the session ends.
- Monitors are an experimental component, so the schema may change between releases.

`${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}` and `${CLAUDE_PROJECT_DIR}` are all substituted into `command`.

## Test it

Run the script by hand first. It should stay alive and print nothing until something happens:

```bash
./scripts/my-new-monitor.sh
```

Then install the plugin locally and confirm it is running:

```text
/plugin marketplace add ./
/plugin install my-new-monitor@aiops-hooks
```

Trigger the thing it watches and confirm Claude is told about it — and, just as important, do ordinary work for a few minutes and confirm it stays quiet.
