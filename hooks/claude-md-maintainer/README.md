# claude-md-maintainer

Keeps CLAUDE.md true and small. A Stop hook collects candidates into a local inbox, and a bundled skill reviews that inbox, verifies each line against the codebase, prunes what has gone stale, and enforces a size budget.

**Event:** `Stop` **Script:** `scripts/capture.py` **Skill:** `skills/claude-md-maintainer/`

## Why this shape

CLAUDE.md is part of every prompt. A wrong line is worse than a missing one, because Claude acts on it. A long file taxes every turn forever. So the interesting work is verification and removal, not collection.

The hook therefore never writes to CLAUDE.md. It appends to `.claude/claude-md-inbox.md` and stops. Anything reaching the real file passes through the skill and your approval.

## Signals it captures

All deterministic, no model call, no cost:

1. **A command that failed and then worked in changed form.** `vendor/bin/phpunit` fails, `ddev exec vendor/bin/phpunit` succeeds. The working form is exactly what belongs in CLAUDE.md.
2. **A correction from you.** A line opening with a negation followed by an instruction ("nee, we gebruiken DDEV, niet docker compose direct").
3. **A search repeated three or more times.** If the same symbol had to be hunted down repeatedly, its location is not obvious.

## Before you rely on it

The Stop payload and the transcript format are not a documented stable API. Verify what your Claude Code version actually sends:

```bash
echo '{}' | ./scripts/capture.py --dump /tmp/stop-payload.json
```

Then install the hook, end a session, and inspect `/tmp/stop-payload.json` for `transcript_path`. If it is absent, the hook degrades to doing nothing and the skill still works on demand.

## Use it

The inbox fills up on its own. When you want to act on it, ask Claude to review the CLAUDE.md inbox. The skill will verify each candidate, look for dead lines in the current file, and present one diff with additions and removals together.

Expect most candidates to be rejected. A session yielding one good line is a good session.

## The inbox stays out of git

The inbox holds verbatim shell commands and things you typed at Claude, so it should never reach a remote. Being inside `.claude/` is not protection: plenty of teams commit that directory on purpose, since it is where project-level Claude config lives.

So on its first write the hook checks whether the path is already ignored, and if not, adds it to `.git/info/exclude`:

```
.claude/claude-md-inbox.md
```

That file is local to your clone and is not tracked, so nobody else sees a change. The hook deliberately does not touch `.gitignore` — a hook editing a tracked file behind your back is the kind of surprise that gets it uninstalled. Outside a git repository it does nothing, and if the path is already covered by your own `.gitignore` it leaves everything alone.

If you would rather have it in the shared `.gitignore`, add the line yourself; the hook will then see it is ignored and skip the exclude file.

## Disable

`/plugin uninstall claude-md-maintainer@aiops-hooks`. Deleting the inbox file is harmless.
