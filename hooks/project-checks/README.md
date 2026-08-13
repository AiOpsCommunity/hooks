# project-checks

Runs the formatter or linter the project already has on the file Claude just edited.

**Event:** `PostToolUse` **Matcher:** `Write|Edit|NotebookEdit` **Script:** `scripts/project-checks.py` (Python 3, no dependencies)

## Trusted directories only

**This hook does nothing until you name the directories it may run in.** When you enable the plugin, Claude Code asks for them:

```text
/plugin install project-checks@aiops-hooks
/plugin enable project-checks          # prompts for trusted directories
```

Point it at where your own work lives, for example `~/Projects`. Everything under a trusted directory is trusted; everything else is silent.

The reason is worth stating plainly, because it is the one thing that could bite you. This hook runs commands defined by the repository it is looking at. `npm run format` executes whatever that project's `package.json` says it should. In a repository you wrote, that is exactly what you want. In a repository you cloned to take a look at, it is somebody else's code running on your machine because Claude touched a file — with your shell, your credentials, no confirmation.

**The list lives in your user settings, never in a project.** An earlier version of this hook took its opt-in from a `.claude/project-checks.json` inside the repository, which is worthless as a trust boundary: any repository you clone can ship that file and grant itself permission. Claude Code refuses to read project-level `pluginConfigs` for exactly this reason, and this hook now follows the same rule.

The trade-off is honest rather than hidden: trusting a directory means trusting everything you put in it. If you clone an unfamiliar repository into a trusted folder, it is trusted. Clone it somewhere else.

Installed by hand instead of as a plugin? Then the list comes from `~/.claude/project-checks.json`:

```json
{ "trustedRoots": ["~/Projects", "~/work"] }
```

## What it does

Inside a trusted directory, it walks up from the edited file to the project root and takes the first thing it recognises:

| Source | Looks for | Runs |
| :-- | :-- | :-- |
| `composer.json` | `cs-fix`, `csfix`, `ecs`, `php-cs-fixer`, `format`, `lint:fix`, `fix` | `composer run <script> -- <file>` |
| `package.json` | `format`, `fmt`, `lint:fix`, `lint-fix`, `prettier`, `lint` | `npm run <script> -- <file>` |
| `.pre-commit-config.yaml` | exists | `pre-commit run --files <file>` |
| nothing | | exits silently |

One file, never the whole repo. Formatting everything because one line changed produces a diff nobody can review, which is why most format-on-write hooks end up removed.

If the tool exits non-zero, its output goes to stderr with exit 2, so Claude sees the error and fixes it in the same turn instead of you finding it at commit time.

Skipped by extension: `.md`, `.mdx`, `.json`, `.lock`, `.txt`, `.csv`, images and archives.

## Makefiles are not auto-detected

`make fmt` takes no file argument, so it would run over the entire repository — the unreviewable diff this hook exists to avoid. Worse, its failures would be about code Claude never touched, and Claude would try to fix them. If your project formats through `make`, say so explicitly:

```json
{ "command": "make fmt-file FILE={file}" }
```

## Configure

Per-project tuning, all keys optional, at `<project>/.claude/project-checks.json`. This file adjusts *how* the hook behaves; it cannot grant trust, and inside an untrusted directory it is never even read.

```json
{
  "command": "vendor/bin/ecs check {file} --fix",
  "skipExtensions": [".twig"],
  "timeout": 60,
  "enabled": true
}
```

`command` overrides detection completely; `{file}` becomes the path relative to the project root. `enabled: false` switches the hook off for this project without deleting the file.

Invalid JSON here is reported rather than ignored: you wrote the file on purpose, so silence would be confusing. The hook exits 1, which shows the message without blocking anything.

## Test it

```bash
CLAUDE_PLUGIN_OPTION_TRUSTED_ROOTS="$PWD" \
  sh -c 'echo "{\"tool_input\":{\"file_path\":\"$PWD/src/Example.php\"}}"' \
  | ./scripts/project-checks.py --dry-run
```

`--dry-run` prints the command it would run and changes nothing. Drop the environment variable and it prints nothing at all — that is the trust gate working.

## Disable

`/plugin uninstall project-checks@aiops-hooks`, or remove the directory from the trusted list. For a single project inside a trusted directory, set `"enabled": false` in its `.claude/project-checks.json`.

The plugin also ships `defaultEnabled: false`, so installing it does not switch it on. You enable it deliberately, and that is when you are asked which directories it may touch.
