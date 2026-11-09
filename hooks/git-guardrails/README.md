# git-guardrails

Blocks git operations that destroy work you cannot get back.

**Event:** `PreToolUse` **Matcher:** `Bash` **Script:** `scripts/git-guardrails.py` (Python 3, no dependencies)

## What it blocks

| Situation | Why |
| :-- | :-- |
| `git push --force` to a protected branch | Overwrites shared history |
| `git branch -D` on a protected branch | Same, and harder to notice |
| `git reset --hard` with uncommitted changes | Those changes are gone, no reflog covers them |
| `git clean -f` with untracked files present | Untracked files are not in git at all |
| `git checkout .` / `git restore .` | Discards every uncommitted change at once |
| `git restore --worktree .` | Same, explicitly on the working tree |
| `git commit` directly on a protected branch | Bypasses review |
| `filter-branch`, `reflog expire`, `gc --prune=now`, `update-ref -d` | History rewrites |

Protected by default: `main`, `master`, `production`, `prod`, `release/*`.

Force pushing a feature branch is allowed, because that is normal work. It prints a one-line nudge towards `--force-with-lease` and lets it through.

Explicitly left alone: `git clean -n` and `--dry-run` (they delete nothing), and `git restore --staged` / `--cached` (they only unstage; the working tree is untouched).

## Two filters, on purpose

The hook config carries `"if": "Bash(git *)"` alongside the `Bash` matcher. That is Claude Code's own permission-rule filter, so the script is not even spawned for `npm test` or `ls`. It saves a process on most Bash calls.

It is not the security boundary, and the script does not rely on it. That filter is documented as best-effort and fails open when it cannot parse a command, so the parsing below runs regardless. Two cheap filters that both fail open are better than one that has to be perfect.

## How it reads a command

The command line is tokenised with `shlex` first, then split on shell operators. That order matters: splitting the raw text on `;` or `&&` first would cut through quoted arguments, so `git commit -m 'fix; done'` would become an unbalanced fragment that the parser rejects — and the whole command would slip past every check without a word. Tokenising first keeps quotes intact, and operators are still recognised without surrounding spaces (`echo hi;git push --force` is two commands).

Leading `NAME=value` assignments and wrappers (`sudo`, `env`, `nohup`, `time`, `nice`) are stripped, so `GIT_DIR=.git git push --force origin main` is still a force push.

Only segments whose program is actually `git` are inspected, so `echo "git push --force"` is left alone.

## What it does not do

- It does not stop `rm -rf`, database drops or deploys. Different hook, different scope.
- It cannot stop you running the same command in your own terminal, which is the intended escape hatch.
- A command it cannot parse at all (an unterminated quote, say) is allowed through. It fails open by design: a guardrail that breaks your session is worse than one that misses an edge case.
- It reasons about the command, not the repository state, except where it has to (`reset --hard` and `clean -f` check whether there is anything to lose).

## Configure

Claude Code asks for three settings when you enable the plugin, and stores them in your user settings:

| Option | Default | What it decides |
| :-- | :-- | :-- |
| `protected_branches` | `main`, `master`, `production`, `prod`, `release/*` | Branches the agent may not force push, delete or commit to directly |
| `allow_force_with_lease` | on | When off, a force push to any branch must use `--force-with-lease` |
| `block_commit_on_protected` | on | Turn off for a solo repository where committing on main is the workflow |

Installed by hand, without the plugin, the same settings go in `~/.claude/git-guardrails.json`:

```json
{
  "protectedBranches": ["main", "develop", "release/*"],
  "allowForceWithLease": true,
  "blockCommitOnProtected": true
}
```

A `.claude/git-guardrails.json` inside a project can only make the hook stricter. Its `protectedBranches` are added to yours, `"allowForceWithLease": false` and `"blockCommitOnProtected": true` switch a check on, and anything that would loosen a check is ignored. These settings decide what the hook lets through, and a file in the project can come from any repository you clone, so it cannot be the place that switches protection off. CONTRIBUTING.md has the same rule for every hook here.

## Test it

```bash
echo '{"cwd":"'"$PWD"'","tool_input":{"command":"git push --force origin main"}}' | ./scripts/git-guardrails.py; echo "exit=$?"   # -> 2
echo '{"cwd":"'"$PWD"'","tool_input":{"command":"git push origin feature/x"}}' | ./scripts/git-guardrails.py; echo "exit=$?"      # -> 0
```

## Disable

`/plugin uninstall git-guardrails@aiops-hooks`, or `claude plugin disable git-guardrails@aiops-hooks --scope local` for one project.
