#!/usr/bin/env python3
"""PostToolUse hook: run whatever formatter or linter the project already has.

Detects the toolchain instead of assuming one. Walks up from the edited file
looking for composer.json, package.json or .pre-commit-config.yaml, takes the
first script it recognises, and runs it on that one file.

One file, not the repo. Formatting an entire codebase because Claude touched one
line produces an unreviewable diff, which is why most format-on-write hooks get
removed.

TRUSTED DIRECTORIES ONLY. This hook executes commands defined by the project it
is looking at — `npm run format` runs whatever that repository's package.json
says. In a repository you did not write, that is somebody else's code running on
your machine because Claude touched a file. So the hook runs only inside
directories you have explicitly marked as trusted, and is silent everywhere else.

That list is deliberately *user* scope, never project scope. An opt-in file
inside the repository would be worthless as a trust boundary, because any
repository you clone can ship one. Claude Code refuses to read project-level
`pluginConfigs` for exactly this reason.

The list comes from, in order:

  1. CLAUDE_PLUGIN_OPTION_TRUSTED_ROOTS, which Claude Code sets from the
     `trusted_roots` userConfig option when the plugin is enabled.
  2. ~/.claude/project-checks.json -> {"trustedRoots": ["~/Projects"]}, for
     people who installed the script by hand rather than as a plugin.

No list means the hook does nothing. It fails closed on purpose.

Exit 0 when the directory is not trusted, the tool succeeds, or nothing is
configured. Exit 2 with the output on stderr when the tool fails, so Claude sees
the error and fixes it in the same turn instead of you finding it at commit time.

Run with --dry-run to print what it would execute and exit.

Per-project tuning at <project>/.claude/project-checks.json, all keys optional:

    {
      "command": "composer run cs-fix -- {file}",
      "skipExtensions": [".md", ".json"],
      "timeout": 60,
      "enabled": true
    }

A "command" overrides detection entirely; {file} becomes the path relative to the
project root. Set "enabled": false to switch the hook off for this project. Note
that this file tunes behaviour but cannot grant trust: inside an untrusted
directory it is never even read.
"""

import json
import os
import re
import shlex
import subprocess
import sys

SKIP_EXTENSIONS = {".md", ".mdx", ".json", ".lock", ".txt", ".csv", ".svg",
                   ".png", ".jpg", ".webp", ".ico", ".pdf", ".zip"}

# Ordered: first match wins. Each entry is (manifest, [(script name, runner)]).
COMPOSER_SCRIPTS = ["cs-fix", "csfix", "ecs", "php-cs-fixer", "format", "lint:fix", "fix"]
NPM_SCRIPTS = ["format", "fmt", "lint:fix", "lint-fix", "prettier", "lint"]

# Makefile targets are deliberately not auto-detected. `make fmt` takes no file
# argument, so it would run over the whole repository and produce exactly the
# unreviewable diff this hook exists to avoid — and its failures would push
# Claude to "fix" code it never touched. A Makefile project sets "command"
# explicitly instead.

MARKERS = ("composer.json", "package.json", ".pre-commit-config.yaml",
           ".pre-commit-config.yml", "Makefile", ".git")

CONFIG = os.path.join(".claude", "project-checks.json")


def find_root(start):
    """Walk up from the edited file to the nearest project marker."""
    path = os.path.dirname(os.path.abspath(start))
    last = None
    while path and path != last:
        for marker in MARKERS:
            if os.path.exists(os.path.join(path, marker)):
                return path
        last, path = path, os.path.dirname(path)
    return None


def json_scripts(path):
    try:
        with open(path) as fh:
            return json.load(fh).get("scripts") or {}
    except (OSError, ValueError):
        return {}


def have(binary):
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory, binary)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return True
    return False


def detect(root, rel):
    """Return (command list, label) or (None, None)."""
    composer = os.path.join(root, "composer.json")
    if os.path.isfile(composer) and have("composer"):
        scripts = json_scripts(composer)
        for name in COMPOSER_SCRIPTS:
            if name in scripts:
                return ["composer", "run", name, "--", rel], f"composer run {name}"

    package = os.path.join(root, "package.json")
    if os.path.isfile(package) and have("npm"):
        scripts = json_scripts(package)
        for name in NPM_SCRIPTS:
            if name in scripts:
                return ["npm", "run", name, "--", rel], f"npm run {name}"

    for name in (".pre-commit-config.yaml", ".pre-commit-config.yml"):
        if os.path.isfile(os.path.join(root, name)) and have("pre-commit"):
            return ["pre-commit", "run", "--files", rel], "pre-commit run"

    return None, None


def trusted_roots():
    """Directories the user has said this hook may run in.

    User scope only. See the module docstring for why a file inside the project
    cannot be the trust boundary.

    The multi-value environment format is not documented precisely, so both a
    JSON array and a separator-delimited string are accepted.
    """
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_TRUSTED_ROOTS", "").strip()
    values = []

    if raw:
        try:
            parsed = json.loads(raw)
            values = parsed if isinstance(parsed, list) else [parsed]
        except ValueError:
            values = re.split(r"[\n" + re.escape(os.pathsep) + r"]", raw)
    else:
        try:
            with open(os.path.expanduser("~/.claude/project-checks.json")) as fh:
                values = json.load(fh).get("trustedRoots") or []
        except (OSError, ValueError, AttributeError):
            values = []

    out = []
    for value in values:
        value = str(value).strip()
        if value:
            out.append(os.path.realpath(os.path.expanduser(value)))
    return out


def is_trusted(root, roots):
    """True when root is one of the trusted directories, or inside one."""
    real = os.path.realpath(root)
    return any(real == t or real.startswith(t + os.sep) for t in roots)


def load_config(root):
    """Per-project tuning. Absent is fine; this file cannot grant trust."""
    path = os.path.join(root, CONFIG)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as fh:
            config = json.load(fh)
    except OSError:
        return {}
    except ValueError as exc:
        # Do not fail silently here: someone wrote this file on purpose and
        # would otherwise wonder why nothing happens. Exit 1 is non-blocking.
        print(f"project-checks: {CONFIG} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(config, dict):
        print(f"project-checks: {CONFIG} must contain a JSON object", file=sys.stderr)
        sys.exit(1)
    return config


def main():
    dry = "--dry-run" in sys.argv

    try:
        payload = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError):
        sys.exit(0)

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(file_path, str) or not file_path:
        sys.exit(0)

    root = find_root(file_path)
    if not root:
        sys.exit(0)

    # The trust check comes before anything in the project is read, so an
    # untrusted repository cannot influence this run at all.
    roots = trusted_roots()
    if not roots or not is_trusted(root, roots):
        sys.exit(0)

    config = load_config(root)
    if config.get("enabled") is False:
        sys.exit(0)

    skip = set(config.get("skipExtensions", [])) | SKIP_EXTENSIONS
    if os.path.splitext(file_path)[1].lower() in skip:
        sys.exit(0)

    if not os.path.isfile(file_path):
        sys.exit(0)

    rel = os.path.relpath(file_path, root)

    if config.get("command"):
        command = shlex.split(config["command"].replace("{file}", shlex.quote(rel)))
        label = config["command"]
    else:
        command, label = detect(root, rel)

    if not command:
        sys.exit(0)

    if dry:
        print(f"would run: {' '.join(command)}  (in {root})")
        sys.exit(0)

    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=config.get("timeout", 60),
        )
    except subprocess.TimeoutExpired:
        print(f"project-checks: {label} timed out on {rel}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"project-checks: could not run {label}: {exc}", file=sys.stderr)
        sys.exit(1)

    if result.returncode == 0:
        sys.exit(0)

    output = (result.stdout + result.stderr).strip()
    if len(output) > 4000:
        output = output[:4000] + "\n... (truncated)"

    print(f"{label} failed on {rel}:\n{output}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
