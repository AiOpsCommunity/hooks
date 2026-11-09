#!/usr/bin/env python3
"""PreToolUse hook: stop irreversible git operations before they run.

Only blocks things that destroy work that is not recoverable through normal git
means: force pushes to protected branches, hard resets over uncommitted changes,
deleting protected branches, wiping untracked files, and history rewrites.

Everything else passes. A guardrail that fires on ordinary work gets uninstalled
within a day, so the bar for blocking is "this loses work permanently".

Exits 2 with the reason on stderr when it blocks, which is what sends the reason
back to Claude. Fails open on anything unexpected.

Config, optional, at .claude/git-guardrails.json in the project:

    {
      "protectedBranches": ["main", "master", "production", "release/*"],
      "allowForceWithLease": true,
      "blockCommitOnProtected": true
    }

Run with --selftest to check every recorded case against temporary repositories.
"""

import contextlib
import fnmatch
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

DEFAULTS = {
    "protectedBranches": ["main", "master", "production", "prod", "release/*"],
    # --force-with-lease refuses to clobber commits you have not seen, so it is
    # allowed on feature branches by default. Protected branches still block.
    "allowForceWithLease": True,
    "blockCommitOnProtected": True,
}

# Tokens that separate one command from the next.
OPERATORS = {"&&", "||", ";", "|", "&", "(", ")"}

# NAME=value prefixes: `GIT_DIR=.git git push` is still a git push.
ENV_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Wrappers that pass the rest of the line through to another command.
WRAPPERS = {"sudo", "nice", "nohup", "time", "env", "command", "xargs"}

# git options that come before the subcommand and take the next token as their
# value. Every other option there is a bare flag (--no-pager, -p, --bare).
GLOBAL_OPTIONS_WITH_VALUE = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
    "--super-prefix",
}

# The global options that change which repository git acts on. The state checks
# repeat them so they read the repository the command will touch. `-c` is left
# out on purpose: a config value such as core.fsmonitor runs a program, and the
# guard must not run anything the user has not approved yet.
REPOSITORY_OPTIONS = {"-C", "--git-dir", "--work-tree"}

# `git push` options whose value is a separate token, so it is not read as the
# remote or a refspec.
PUSH_OPTIONS_WITH_VALUE = {
    "-o", "--push-option", "--repo", "--receive-pack", "--exec",
}


class Blocked(Exception):
    def __init__(self, reason, suggestion):
        super().__init__(reason)
        self.reason = reason
        self.suggestion = suggestion


def split_global_options(segment):
    """Separate `git -C dir --no-pager push ...` into the repository options and
    `["git", "push", ...]`.

    Without this the first option is taken for the subcommand, and
    `git -C . push --force origin main` passes every check.
    """
    repository = []
    i = 1
    while i < len(segment) and segment[i].startswith("-"):
        token = segment[i]
        name, has_value, _ = token.partition("=")
        if token in GLOBAL_OPTIONS_WITH_VALUE:
            if i + 1 >= len(segment):
                return None
            if token in REPOSITORY_OPTIONS:
                repository += [token, segment[i + 1]]
            i += 2
            continue
        if has_value and name in REPOSITORY_OPTIONS:
            repository.append(token)
        i += 1
    if i >= len(segment):
        return None
    return repository, [segment[0]] + segment[i:]


def git_commands(command):
    """Split a shell command line into the git invocations it contains.

    Tokenising comes first, splitting on operators second. Doing it the other
    way round cuts straight through quoted arguments: `git commit -m 'fix; done'`
    becomes the fragment `git commit -m 'fix`, shlex refuses it, and the whole
    command escapes every check below. That failure was silent, which is the
    worst property a guardrail can have.

    punctuation_chars makes the lexer treat `;`, `&&` and friends as their own
    tokens even without surrounding spaces, so `a;git push` splits correctly
    while `-m 'fix; done'` stays one argument.

    Returns (repository options, tokens) pairs, where tokens starts with the git
    executable followed directly by the subcommand.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        # shlex treats # as a comment marker by default; a shell only does that
        # at the start of a word. Leaving it on would silently truncate
        # `git commit -m fix#123` and skip everything after it.
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return []

    segments = []
    current = []
    for token in tokens:
        if token in OPERATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)

    out = []
    for segment in segments:
        # Strip NAME=value prefixes and wrapper programs until the real command.
        while segment and (ENV_PREFIX.match(segment[0])
                           or os.path.basename(segment[0]) in WRAPPERS):
            segment = segment[1:]
        if len(segment) >= 2 and os.path.basename(segment[0]) == "git":
            split = split_global_options(segment)
            if split:
                out.append(split)
    return out


def load_config(cwd):
    cfg = dict(DEFAULTS)
    path = os.path.join(cwd, ".claude", "git-guardrails.json")
    try:
        with open(path) as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def git(cwd, *args):
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def is_protected(branch, patterns):
    if not branch:
        return False
    return any(fnmatch.fnmatch(branch, p) for p in patterns)


def block(reason, suggestion):
    raise Blocked(reason, suggestion)


def short_flags(tokens):
    """Every letter given as a short flag, so `-fu` counts as both -f and -u."""
    letters = set()
    for token in tokens:
        if re.fullmatch(r"-[a-zA-Z]+", token):
            letters.update(token[1:])
    return letters


def branch_name(ref, current):
    if ref in ("", "HEAD"):
        return current
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    return ref


def check_push(tokens, cfg, current):
    options = tokens[2:]
    letters = short_flags(options)
    forced = "--force" in options or "f" in letters
    lease = any(t.startswith("--force-with-lease") for t in options)
    deleting = "--delete" in options or "d" in letters
    protected = cfg["protectedBranches"]
    advice = (
        "Push to a feature branch and open a pull request. If this is "
        "genuinely intended, run it yourself outside Claude Code."
    )

    if "--mirror" in options:
        block("`git push --mirror` overwrites and deletes every remote branch", advice)
    if (forced or lease) and ("--all" in options or "--branches" in options):
        block("force push of every branch, protected ones included", advice)

    positional = []
    skip = False
    for token in options:
        if skip:
            skip = False
        elif token in PUSH_OPTIONS_WITH_VALUE:
            skip = True
        elif not token.startswith("-"):
            positional.append(token)

    # The first positional is the remote; without refspecs git pushes the
    # current branch.
    refspecs = positional[1:] or [current or ""]
    targets = []
    for spec in refspecs:
        plus = spec.startswith("+")
        spec = spec.lstrip("+")
        source, colon, destination = spec.partition(":")
        target = branch_name(destination if colon else source, current)
        # `git push origin :main` is the old spelling of --delete.
        removes = deleting or (colon and source == "")
        targets.append(target)

        if removes and is_protected(target, protected):
            block(f"deleting protected branch '{target}' on the remote", advice)
        if (forced or lease or plus) and is_protected(target, protected):
            block(f"force push to protected branch '{target}'", advice)

    if not forced:
        return
    shown = ", ".join(t for t in targets if t) or "the current branch"

    if not lease and not cfg["allowForceWithLease"]:
        block(
            f"force push to '{shown}'",
            "Use --force-with-lease, which refuses to overwrite commits you "
            "have not seen.",
        )

    if not lease:
        # Allowed, but say something useful.
        print(
            "git-guardrails: prefer --force-with-lease over --force.",
            file=sys.stderr,
        )


def check_delete_branch(tokens, cfg):
    options = tokens[2:]
    letters = short_flags(options)
    force_delete = "D" in letters or (
        ("d" in letters or "--delete" in options)
        and ("f" in letters or "--force" in options)
    )
    if not force_delete:
        return
    for t in options:
        if not t.startswith("-") and is_protected(t, cfg["protectedBranches"]):
            block(
                f"deleting protected branch '{t}'",
                "Protected branches are deleted by a human, not by an agent.",
            )


def check_reset(tokens, cwd, repository):
    if "--hard" not in tokens:
        return
    dirty = git(cwd, *repository, "status", "--porcelain")
    if dirty:
        count = len(dirty.splitlines())
        block(
            f"git reset --hard with {count} uncommitted change(s)",
            "Run `git stash` first, or commit to a scratch branch. The changes "
            "cannot be recovered after a hard reset.",
        )


def has_force_flag(tokens):
    """True when -f or --force is present, without matching an f inside a value.

    Concatenating every dash-prefixed token and searching for "f" reads the f of
    `--exclude=foo` as the force flag, which blocks `git clean -nd --exclude=foo`
    — a dry run that deletes nothing.
    """
    return "--force" in tokens or "f" in short_flags(tokens)


def check_clean(tokens, cwd, repository):
    # -n / --dry-run only lists what would go; nothing is deleted.
    if "-n" in tokens or "--dry-run" in tokens:
        return
    if not has_force_flag(tokens):
        return
    untracked = git(cwd, *repository, "clean", "-nd")
    if untracked:
        count = len(untracked.splitlines())
        block(
            f"git clean would delete {count} untracked path(s)",
            "Untracked files are not in git and cannot be recovered. Review "
            "`git clean -nd` output first.",
        )


def check_commit(tokens, cfg, current):
    if not cfg["blockCommitOnProtected"]:
        return
    if is_protected(current, cfg["protectedBranches"]):
        block(
            f"committing directly to protected branch '{current}'",
            f"Create a branch first: git checkout -b <name>. Current branch is "
            f"'{current}'.",
        )


def check_history_rewrite(tokens):
    """Match on the subcommand, not on the text of the line.

    Searching the whole command for "filter-branch" blocks
    `git commit -m 'stop using filter-branch'`, which rewrites nothing. The
    subcommand is the only place these can actually appear as an instruction.
    """
    advice = "History rewrites are a human decision. Run it yourself if you are sure."
    sub = tokens[1]
    rest = tokens[2:]

    if sub == "filter-branch":
        block("`git filter-branch` rewrites every commit", advice)

    if sub == "reflog" and rest and rest[0] == "expire":
        block(
            "`git reflog expire` destroys the reflog, the last recovery route",
            advice,
        )

    if sub == "gc":
        for token in rest:
            # --prune=never is the safe one; now/all drop unreachable objects.
            if token.startswith("--prune=") and token != "--prune=never":
                block(f"`git gc {token}` drops unreachable objects immediately", advice)

    if sub == "update-ref" and "-d" in rest:
        block("`git update-ref -d` deletes a ref directly", advice)


def check_checkout_discard(tokens):
    # git checkout . / git restore . discards every uncommitted change
    if tokens[-1] not in (".", "--", "*"):
        return
    if "-b" in tokens:
        return
    # --staged / --cached unstage only: the index changes, the working tree does
    # not, and nothing is lost. Blocking those is a false positive.
    staged_only = ("--staged" in tokens or "--cached" in tokens)
    if staged_only and "--worktree" not in tokens and "-W" not in tokens:
        return
    block(
        f"`{' '.join(tokens)}` discards all uncommitted changes",
        "Stash first if there is anything worth keeping.",
    )


def evaluate(command, cwd):
    """Raise Blocked for the first git invocation in `command` that loses work."""
    cfg = load_config(cwd)

    for repository, tokens in git_commands(command):
        check_history_rewrite(tokens)

        sub = tokens[1]
        if sub in ("push", "commit"):
            current = git(cwd, *repository, "rev-parse", "--abbrev-ref", "HEAD")
        if sub == "push":
            check_push(tokens, cfg, current)
        elif sub == "branch":
            check_delete_branch(tokens, cfg)
        elif sub == "reset":
            check_reset(tokens, cwd, repository)
        elif sub == "clean":
            check_clean(tokens, cwd, repository)
        elif sub == "commit":
            check_commit(tokens, cfg, current)
        elif sub in ("checkout", "restore"):
            check_checkout_discard(tokens)


# (repository, command, expected). "main" is on main with a modified tracked
# file and an untracked one; "feature" is on feature and clean. {main} and
# {feature} expand to their paths.
SELFTEST = [
    ("feature", "git push --force origin main", "block"),
    ("feature", "git -C . push --force origin main", "block"),
    ("feature", "git --no-pager push -f origin main", "block"),
    ("feature", "git -c color.ui=never push --force origin main", "block"),
    ("feature", "git --git-dir=.git push -f origin main", "block"),
    ("feature", "git push -fu origin main", "block"),
    ("feature", "git push origin +main", "block"),
    ("feature", "git push origin +HEAD:main", "block"),
    ("feature", "git push --force origin feature main", "block"),
    ("feature", "git push --force origin HEAD:refs/heads/main", "block"),
    ("feature", "git push --force-with-lease origin main", "block"),
    ("feature", "git push origin --delete main", "block"),
    ("feature", "git push origin -d main", "block"),
    ("feature", "git push origin :main", "block"),
    ("feature", "git push --mirror origin", "block"),
    ("feature", "git push --force --all origin", "block"),
    ("feature", "GIT_DIR=.git git push --force origin main", "block"),
    ("feature", "cd sub; git push -f origin main", "block"),
    ("main", "git push --force", "block"),
    ("main", "git push -f origin HEAD", "block"),
    ("main", "git reset --hard", "block"),
    ("main", "git -C . reset --hard", "block"),
    ("feature", "git -C {main} reset --hard", "block"),
    ("main", "git clean -fd", "block"),
    ("feature", "git -C {main} clean -fd", "block"),
    ("main", "git commit -m wip", "block"),
    ("feature", "git -C {main} commit -m wip", "block"),
    ("feature", "git branch -D main", "block"),
    ("feature", "git branch -df main", "block"),
    ("feature", "git branch --delete --force main", "block"),
    ("feature", "git filter-branch --tree-filter true HEAD", "block"),
    ("feature", "git --no-pager filter-branch --tree-filter true HEAD", "block"),
    ("feature", "git reflog expire --all", "block"),
    ("main", "git checkout .", "block"),
    ("main", "git restore .", "block"),
    ("feature", "git push origin feature", "allow"),
    ("feature", "git push origin main", "allow"),
    ("feature", "git push -u origin feature", "allow"),
    ("feature", "git push -f origin feature", "allow"),
    ("feature", "git push --force-with-lease origin feature", "allow"),
    ("feature", "git push origin feature:feature-copy", "allow"),
    ("feature", "git push -o ci.skip origin feature", "allow"),
    ("feature", "git push origin --delete old-feature", "allow"),
    ("main", "git push --force origin feature", "allow"),
    ("feature", "git -C . status", "allow"),
    ("feature", "git --no-pager log --oneline", "allow"),
    ("feature", "git -c core.pager=cat diff", "allow"),
    ("feature", "git reset --hard", "allow"),
    ("feature", "git -C {feature} commit -m wip", "allow"),
    ("main", "git clean -nd", "allow"),
    ("main", "git clean -nd --exclude=foo", "allow"),
    ("main", "git restore --staged .", "allow"),
    ("feature", "git branch -d old-feature", "allow"),
    ("feature", "git branch -D old-feature", "allow"),
    ("feature", "git commit -m 'stop using filter-branch'", "allow"),
    ("feature", "git commit -m 'fix; git push --force origin main'", "allow"),
    ("feature", "echo 'git push --force origin main'", "allow"),
    ("feature", "git gc --prune=never", "allow"),
]


def make_repository(path, branch, dirty):
    def run(*args):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

    os.makedirs(path)
    run("init", "-q", "-b", branch)
    run("config", "user.email", "selftest@example.invalid")
    run("config", "user.name", "selftest")
    with open(os.path.join(path, "tracked.txt"), "w") as fh:
        fh.write("one\n")
    run("add", "tracked.txt")
    run("commit", "-q", "-m", "init")
    if dirty:
        with open(os.path.join(path, "tracked.txt"), "a") as fh:
            fh.write("two\n")
        with open(os.path.join(path, "untracked.txt"), "w") as fh:
            fh.write("new\n")


def selftest():
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        repos = {
            "main": os.path.join(tmp, "main"),
            "feature": os.path.join(tmp, "feature"),
        }
        make_repository(repos["main"], "main", dirty=True)
        make_repository(repos["feature"], "feature", dirty=False)

        for repo, command, expected in SELFTEST:
            command = command.format(**repos)
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    evaluate(command, repos[repo])
                    got = "allow"
                except Blocked:
                    got = "block"
            if got != expected:
                failures += 1
                print(f"FAIL [{repo}] {command}: expected {expected}, got {got}")

    print(f"{len(SELFTEST) - failures}/{len(SELFTEST)} cases pass")
    return 1 if failures else 0


def main():
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())

    try:
        payload = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError):
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or "git" not in command:
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    try:
        evaluate(command, cwd)
    except Blocked as blocked:
        print(
            f"Blocked by git-guardrails: {blocked.reason}\n{blocked.suggestion}",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
