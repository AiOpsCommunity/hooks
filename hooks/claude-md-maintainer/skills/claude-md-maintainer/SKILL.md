---
name: claude-md-maintainer
description: Review the CLAUDE.md inbox, verify candidate lines against the codebase, prune stale or dead lines, and keep CLAUDE.md within a size budget. Use this skill whenever the user mentions CLAUDE.md, project memory, the claude-md inbox, or asks why Claude keeps forgetting or misremembering something about a project. Also use when CLAUDE.md has grown long, when lines in it reference commands or paths that may no longer exist, or after a session that revealed context Claude should have had.
---

# CLAUDE.md maintainer

CLAUDE.md sits in every prompt. A wrong line is worse than a missing one, because Claude acts on it with confidence, and a bloated file costs tokens on every single turn forever. This skill therefore does two jobs that matter more than adding content: it verifies before adding, and it removes what has gone stale.

The companion Stop hook collects candidates into `.claude/claude-md-inbox.md`. It never writes to CLAUDE.md. That is this skill's job, and only with the user's approval.

## Workflow

### 1. Read the inbox and the file

```bash
cat .claude/claude-md-inbox.md 2>/dev/null
find . -maxdepth 3 -name 'CLAUDE.md' -o -maxdepth 3 -name '.claude.local.md' 2>/dev/null
wc -l CLAUDE.md 2>/dev/null
```

No inbox is fine. The pruning pass below is worth running on its own.

### 2. Verify every candidate before it goes in

A candidate is a hint, not a fact. Check each one against the repository, and drop anything that fails:

| Candidate type | How to verify |
| :-- | :-- |
| A command | The script exists in `package.json`, `composer.json`, `Makefile`, or the binary exists |
| A path or directory convention | The path exists and is not a one-off |
| A correction from the user | It contradicts nothing already in CLAUDE.md, and still holds in the current code |
| A repeated search | The thing being searched for is genuinely non-obvious from the directory structure |

Then apply the harder test, which most candidates fail: **would this have changed what Claude did?** A line stating that the project uses TypeScript when every file ends in `.ts` changes nothing. A line stating that tests must run through `ddev exec` because the host has no PHP changes everything.

Drop anything that is:

- Discoverable in under two seconds from the file tree.
- A one-off fix unlikely to recur.
- Already implied by another line.
- A general best practice rather than something specific to this project.

Expect to reject most of the inbox. A session that yields one good line is a good session.

### 3. Prune, and be specific about why

This is the part nothing else does. Go through CLAUDE.md line by line and check each claim:

```bash
# Commands referenced in CLAUDE.md that no longer exist
grep -oE '`[a-z]+ run [a-z:_-]+`' CLAUDE.md
cat package.json composer.json 2>/dev/null | python3 -c "import json,sys; ..."
# Paths referenced that are gone
grep -oE '`[a-zA-Z0-9_/.-]+/`' CLAUDE.md
```

Flag for removal:

- A referenced script, binary or path that does not exist. This is objectively dead, and it is actively harmful because Claude will try it.
- A line describing a framework, library or service that no longer appears in the manifests.
- Two lines saying the same thing.
- Instructions that duplicate what a linter or hook already enforces.
- Lines about a migration or refactor that has since completed.

Show each removal with the evidence: "line 34 mentions `npm run test:unit`, which is not in package.json (scripts: test, test:e2e, build)". Never remove on suspicion alone.

### 4. Enforce a budget

Propose a limit if none exists. Around 150 lines for a project root file is a reasonable starting point, less for a subdirectory file. Once at the limit, the rule is net-zero: a new line requires a line out. That forces a real comparison instead of endless accretion, and the comparison is usually easy because the weakest line is obvious.

Report the arithmetic: "CLAUDE.md is 168 lines, budget 150. Adding 2, removing 21, ends at 149."

### 5. Route each line to the right file

| Destination | For |
| :-- | :-- |
| `CLAUDE.md` | Team-shared truths about this project, committed to git |
| `.claude.local.md` | Your machine, your paths, your preferences, gitignored |
| A subdirectory `CLAUDE.md` | Context that only applies to one package in a monorepo |
| Nowhere | Everything else |

A line about a local Docker socket path belongs in the local file, not the shared one. Getting this wrong is how shared files fill up with one person's setup.

### 6. Present one diff, then apply

Show additions and removals together as a single diff, with a one-line reason per change. Ask for approval. Apply only what is approved, then clear the processed entries from the inbox so they are not proposed again.

Never write to CLAUDE.md without explicit approval in the current turn, and never rewrite lines the user did not ask you to touch. Their wording is theirs.

## Writing style for entries

One line per fact, imperative, specific, no prose:

```
- Tests run through `ddev exec vendor/bin/phpunit`; the host has no PHP.
- Plugin code lives in custom/plugins/, not src/. src/ is core and is gitignored.
- Never edit files in var/cache/; they are regenerated on every build.
```

Not:

```
- This project uses PHP and Symfony. It is important to write clean, testable
  code and to follow the existing conventions in the codebase.
```

The second one costs tokens on every prompt and changes nothing.

## When there is no CLAUDE.md yet

Do not generate one from a codebase scan. That produces a file full of things Claude could have read from the tree anyway. Start empty or with three lines, and let the inbox fill it with things that actually came up. A short true file beats a long plausible one.
