# ci-watch

Watches GitHub Actions for the branch you are on, and tells Claude when a run finishes.

**Command:** `scripts/ci-watch.sh` (Bash, needs the `gh` CLI)
**Watches:** the latest workflow run for the current branch

## What it does

You push, keep working, and four minutes later the pipeline goes red. Normally you find out when you next look, and then you paste the failure into the session. This closes that gap: Claude is told directly.

```
CI failure on add-auth — Tests. https://github.com/owner/repo/actions/runs/123
```

Nothing else is printed. Not the workflow starting, not each poll, not a repeat of a failure it has already mentioned.

## What it reports, and what it swallows

Two rules decide whether a line is worth interrupting for:

| Situation | Reported |
| :-- | :-- |
| A run fails, times out, or fails at startup | **Yes**, always. That is the point. |
| A run passes, and the monitor saw it running first | **Yes** — you were waiting for it |
| A run passes that was already finished when the monitor first looked | No. Green CI you never knew was pending is not news |
| The same run stays red across polls | No, announced once |
| A run is queued or in progress | No |
| A run is cancelled, skipped, or neutral | No |
| No runs yet, or the API call fails | No. A transient network error is not Claude's business |

The "saw it running first" rule is what keeps this quiet. Open a session on a branch whose CI passed last week and the monitor says nothing at all.

## Requirements

The `gh` CLI, authenticated (`gh auth status`). If it is missing, or this is not a GitHub repository, the monitor says so **once** and then stays silent for the rest of the session rather than repeating itself every minute.

## Polling

Every 60 seconds while nothing is running, every 20 while a run is in progress. At the fastest configurable setting that is roughly 720 calls an hour, well inside the authenticated rate limit.

## Configure

Optional, at `<plugin-data>/ci-watch.json`:

```json
{ "idleSeconds": 60, "activeSeconds": 20, "reportSuccess": true }
```

Set `reportSuccess` to `false` if you only ever want to hear about failures. Intervals are clamped between 5 and 3600 seconds.

Monitors do not receive `CLAUDE_PLUGIN_OPTION_<KEY>` and `${user_config.*}` is not substituted into a monitor command, so a file the script owns is the documented way to configure one. The plugin data directory survives plugin updates, unlike the plugin root.

## Test it

Run it by hand in a repository with a GitHub remote. It should print nothing at all while CI is idle:

```bash
./scripts/ci-watch.sh
```

Then push a branch with a failing job and confirm exactly one line appears once the run completes, and that nothing further appears while it stays red.

To check the quiet paths without waiting on real CI, run it in a directory that is not a git repository (expect complete silence) and with `gh` off your `PATH` (expect one explanatory line, then silence).

## What it does not do

- It only looks at the **latest** run for the branch. A branch with several workflows reports whichever finished most recently, not one line per workflow.
- It does not fetch logs or say which step failed. It gives you the URL; Claude can fetch the detail if you want it.
- It does not notice a run on a branch you are not on. Switch branches and it follows you.
- It stops when the session ends, and a plugin disabled mid-session leaves the process running until then.

## Disable

`/plugin uninstall ci-watch@aiops-hooks`.
