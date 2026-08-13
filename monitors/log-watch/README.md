# log-watch

Watches the log files you name, and reports only the lines matching the patterns you chose.

**Command:** `scripts/log-watch.py` (Python 3, no dependencies)
**Watches:** whatever is in your config and exists in the current project

## What it does

You are working on a feature, a request fails somewhere in the stack, and the reason lands in a log file. Normally you notice later, go find the log, and paste the relevant lines in. This closes that gap:

```
[var/log/dev.log] 2026-08-12 14:02:11 CRITICAL Uncaught TypeError in OrderConverter.php:88
```

Nothing else. Not every line, not the ones that do not match, not the same line twice.

## Configure it first

It does nothing until you tell it what to watch. Create `<plugin-data>/log-watch.json`:

```json
{
  "watch": [
    { "file": "var/log/dev.log",
      "match": ["CRITICAL", "Fatal error", "Uncaught"],
      "ignore": ["deprecated"] },
    { "file": "storage/logs/laravel.log",
      "match": ["ERROR", "CRITICAL"] },
    { "file": "log/development.log",
      "match": ["^F, \\[", "Error"] }
  ]
}
```

The plugin says once, in your first session after installing, where that file goes. It does not repeat itself afterwards.

**Paths are relative to the project you are in, and missing files are skipped silently.** That is what makes one config work everywhere: list the log locations of every framework you use, and in each project only the ones that exist are watched. The example above covers Symfony or Shopware, Laravel, and Rails at the same time; in a Laravel project the other two simply do not apply.

`match` and `ignore` are regular expressions, matched case-insensitively. `ignore` is checked after `match`, so it carves exceptions out of a broad pattern.

## Why the config is yours and not the project's

This is the part worth understanding before you trust it.

A monitor that took its watch list from a file inside the repository would be trivially abusable: any repository you clone could ship a `.claude/log-watch.json` pointing at `~/.ssh/id_rsa` with a pattern of `"."`, and your private key would be read straight into Claude's context. Nothing about "it is only reading a log file" stops that.

So the config lives under the plugin data directory, in user scope. Claude Code refuses to read project-level `pluginConfigs` for the same reason, and monitors receive no `CLAUDE_PLUGIN_OPTION_<KEY>` and cannot use `${user_config.*}` — so a file the script owns is both the documented way to configure a monitor and the safe one.

As a second line of defence the script refuses to read anything that looks like a credential store — `.env`, `.pem`, `.key`, `id_rsa`, `credentials`, anything under `.ssh/`, `.gnupg/` or `.aws/` — and says so rather than failing quietly. That guard is there for your own typos, not for an attacker.

## How it stays quiet

A monitor that floods the session gets uninstalled, so most of this script is restraint:

| Rule | Why |
| :-- | :-- |
| Only lines matching `match` are printed | An empty `match` is rejected outright: "print everything" is the one thing a monitor must never do |
| The same line twice in a row is printed once | Retry loops repeat themselves |
| At most 5 matching lines a minute per file | A log that explodes should not turn the session into noise |
| Held-back lines are summarised once when the window clears | `[app.log] 42 more matching line(s) were suppressed` |
| Lines longer than 300 characters are truncated | A stack trace is not a notification |
| Only lines written after the monitor started | Opening a session does not replay last week |

All four numbers are configurable: `pollSeconds` (1–60, default 2), `maxLinesPerMinute` (1–60, default 5), `maxLineLength` (80–2000, default 300).

## Test it

```bash
mkdir -p /tmp/lw && printf '{"pollSeconds":1,"watch":[{"file":"app.log","match":["ERROR"]}]}' > /tmp/lw/log-watch.json
cd /tmp && touch app.log
./scripts/log-watch.py /tmp/lw /tmp &
echo "INFO nothing to see" >> app.log     # no output
echo "ERROR something broke" >> app.log   # one line
```

Then check the quiet paths, which matter more: point it at a file that does not exist (silence), and let it run for a few minutes during ordinary work (silence).

## What it does not do

- It does not parse log formats. A line is a line; multi-line stack traces are reported as their first matching line only.
- It does not follow a log through a symlink change, only through truncation and rotation of the path itself.
- It cannot watch a file outside the project unless you give an absolute path, and it will still refuse credential-shaped ones.
- It runs only in interactive CLI sessions, like every monitor.

## Disable

`/plugin uninstall log-watch@aiops-hooks`, or empty the `watch` array to keep the plugin and stop the watching.
