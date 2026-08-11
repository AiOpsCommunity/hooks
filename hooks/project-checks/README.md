# project-checks

Runs the formatter or linter the project already has on the file Claude just edited.

**Event:** `PostToolUse` **Matcher:** `Write|Edit|NotebookEdit` **Script:** `scripts/project-checks.py` (Python 3, no dependencies)

## Opt in first

**This hook does nothing until a project opts in.** Add one file:

```bash
mkdir -p .claude && echo '{}' > .claude/project-checks.json
```

That empty object is the whole opt-in. Detection still does the work — you are not specifying commands, only granting permission once.

The reason is worth stating plainly, because it is the one thing that could bite you. This hook runs commands defined by the repository it is looking at. `npm run format` executes whatever that project's `package.json` says it should. In a repository you wrote, that is exactly what you want. In a repository you cloned to take a look at, it is somebody else's code running on your machine because Claude touched a file — with your shell, your credentials, no confirmation. Making it opt-in means opening an unfamiliar repo does nothing at all.

## What it does

Once a project has opted in, it walks up from the edited file to the project root and takes the first thing it recognises:

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

All keys optional, at `.claude/project-checks.json`:

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
mkdir -p .claude && echo '{}' > .claude/project-checks.json
echo '{"tool_input":{"file_path":"'"$PWD"'/src/Example.php"}}' | ./scripts/project-checks.py --dry-run
```

`--dry-run` prints the command it would run and changes nothing. Without the config file, it prints nothing at all — that is the opt-in working.

## Disable

`/plugin uninstall project-checks@aiops-hooks`. For a single project, set `"enabled": false` or delete `.claude/project-checks.json`.
