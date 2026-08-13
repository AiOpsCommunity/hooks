#!/usr/bin/env python3
"""log-watch - report the log lines you care about, and nothing else.

Contract: stdout is a message to Claude. So this prints a line only when it
matches a pattern you configured, and it works hard not to print more than that.

The configuration lives in YOUR config, not in the project. That is deliberate.
A monitor that took its watch list from a file inside the repository would let
any repository you clone point it at ~/.ssh/id_rsa with a pattern of ".", and
your private key would be read straight into Claude's context. Monitors receive
no CLAUDE_PLUGIN_OPTION_* and cannot use ${user_config.*}, so a file the script
owns under the plugin data directory is both the documented way to configure one
and the safe one.

Config at <plugin-data>/log-watch.json:

    {
      "watch": [
        { "file": "var/log/dev.log",
          "match": ["CRITICAL", "Fatal error", "Uncaught"],
          "ignore": ["deprecated"] },
        { "file": "storage/logs/laravel.log",
          "match": ["ERROR", "CRITICAL"] }
      ],
      "pollSeconds": 2,
      "maxLinesPerMinute": 5,
      "maxLineLength": 300
    }

Paths are relative to the project you are working in, so one config covers every
project you own: list the log locations of every framework you use, and in each
project only the files that actually exist are watched. Patterns are regular
expressions, matched case-insensitively.

Usage: log-watch.py <plugin-data-dir> [project-dir]
"""

import json
import os
import re
import sys
import time

CONFIG_NAME = "log-watch.json"
HINT_MARKER = ".log-watch-hint-shown"

DEFAULTS = {
    "pollSeconds": 2,
    "maxLinesPerMinute": 5,
    "maxLineLength": 300,
}

# Files this monitor refuses to read, whatever the config says. The config is
# yours, so this is a guard against a slip rather than an attacker: a typo that
# points at a credential store should not quietly stream it into the session.
FORBIDDEN = re.compile(
    r"(^|/)(\.env(\..*)?|\.netrc|\.npmrc|\.pypirc|id_[rd]sa|id_ecdsa|id_ed25519"
    r"|credentials(\.json)?|.*\.pem|.*\.key|.*\.p12|.*\.pfx)$"
    r"|/\.ssh/|/\.gnupg/|/\.aws/",
    re.IGNORECASE,
)


def say(message):
    """Everything printed here reaches Claude. Nothing else writes to stdout."""
    print(message, flush=True)


def idle_forever():
    """Stay alive without speaking again.

    A monitor that exits has silently stopped watching, which is worse than one
    that is quiet on purpose.
    """
    while True:
        time.sleep(3600)


def clamp(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def load_config(data_dir):
    """Return (entries, settings), or None when there is nothing to do."""
    path = os.path.join(data_dir, CONFIG_NAME) if data_dir else ""

    if not path or not os.path.isfile(path):
        # Say this once, ever. Repeating it every session would be nagging, and
        # staying silent forever would leave someone wondering why nothing
        # happens after installing.
        marker = os.path.join(data_dir, HINT_MARKER) if data_dir else ""
        if marker and not os.path.exists(marker):
            try:
                os.makedirs(data_dir, exist_ok=True)
                with open(marker, "w") as fh:
                    fh.write("shown\n")
                say(
                    f"log-watch is installed but not configured. Create {path} "
                    'with, for example: {"watch": [{"file": "var/log/dev.log", '
                    '"match": ["CRITICAL", "Fatal error"]}]}'
                )
            except OSError:
                pass
        return None

    try:
        with open(path) as fh:
            config = json.load(fh)
    except (OSError, ValueError) as exc:
        say(f"log-watch: {path} could not be read ({exc}). Watching nothing.")
        return None

    if not isinstance(config, dict):
        say(f"log-watch: {path} must contain a JSON object. Watching nothing.")
        return None

    settings = {
        "pollSeconds": clamp(config.get("pollSeconds"), 2, 1, 60),
        "maxLinesPerMinute": clamp(config.get("maxLinesPerMinute"), 5, 1, 60),
        "maxLineLength": clamp(config.get("maxLineLength"), 300, 80, 2000),
    }

    entries = []
    problems = []
    for raw in config.get("watch") or []:
        if not isinstance(raw, dict):
            problems.append("an entry in 'watch' is not an object")
            continue

        target = raw.get("file")
        patterns = raw.get("match")

        if not target or not isinstance(target, str):
            problems.append("an entry has no 'file'")
            continue
        # An empty match list would mean "print every line", which is the one
        # thing a monitor must never do.
        if not patterns or not isinstance(patterns, list):
            problems.append(f"{target} has no 'match' patterns, so it is skipped")
            continue

        try:
            compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
            ignored = [re.compile(p, re.IGNORECASE) for p in (raw.get("ignore") or [])]
        except re.error as exc:
            problems.append(f"{target} has an invalid pattern ({exc})")
            continue

        entries.append({"file": target, "match": compiled, "ignore": ignored})

    for problem in problems:
        say(f"log-watch: {problem}")

    return (entries, settings) if entries else None


def resolve(entries, project_dir):
    """Keep the entries whose file exists here and is safe to read.

    A config listing the log locations of five frameworks is normal: in any one
    project, most of them simply are not there.
    """
    resolved = []
    for entry in entries:
        path = entry["file"]
        full = path if os.path.isabs(path) else os.path.join(project_dir, path)
        full = os.path.realpath(full)

        if FORBIDDEN.search(full):
            say(f"log-watch: refusing to watch {path}; it looks like a credential file.")
            continue
        if not os.path.isfile(full):
            continue

        resolved.append({**entry, "path": full, "label": path})
    return resolved


class Tail:
    """Follows one file, surviving truncation and rotation."""

    def __init__(self, path):
        self.path = path
        self.handle = None
        self.inode = None
        self._open(seek_to_end=True)

    def _open(self, seek_to_end):
        try:
            handle = open(self.path, "r", errors="replace")
        except OSError:
            self.handle = None
            return
        if seek_to_end:
            handle.seek(0, os.SEEK_END)
        self.handle = handle
        try:
            self.inode = os.fstat(handle.fileno()).st_ino
        except OSError:
            self.inode = None

    def read_new(self):
        if self.handle is None:
            self._open(seek_to_end=False)
            if self.handle is None:
                return []

        try:
            stat = os.stat(self.path)
        except OSError:
            return []

        # Rotated (new inode) or truncated (shorter than our position): reopen
        # from the start, because the lines we have not seen are at the front.
        if stat.st_ino != self.inode or stat.st_size < self.handle.tell():
            self.handle.close()
            self._open(seek_to_end=False)
            if self.handle is None:
                return []

        lines = self.handle.readlines()
        return [line.rstrip("\n") for line in lines if line.strip()]


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else ""
    project_dir = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()

    loaded = load_config(data_dir)
    if loaded is None:
        idle_forever()

    entries, settings = loaded
    watched = resolve(entries, project_dir)
    if not watched:
        # Configured, but none of those files are in this project. Normal, and
        # not worth a word.
        idle_forever()

    tails = {w["path"]: Tail(w["path"]) for w in watched}
    last_line = {}      # path -> last line emitted, to drop repeats
    window = {}         # path -> [timestamps of lines emitted in the last minute]
    suppressed = {}     # path -> count held back in the current window

    while True:
        now = time.time()

        for entry in watched:
            path = entry["path"]
            for line in tails[path].read_new():
                if not any(p.search(line) for p in entry["match"]):
                    continue
                if any(p.search(line) for p in entry["ignore"]):
                    continue
                if line == last_line.get(path):
                    continue

                recent = [t for t in window.get(path, []) if now - t < 60]

                # A log that explodes must not turn the session into noise. Past
                # the budget, hold lines back and say so once when it clears.
                if len(recent) >= settings["maxLinesPerMinute"]:
                    window[path] = recent
                    suppressed[path] = suppressed.get(path, 0) + 1
                    continue

                held = suppressed.pop(path, 0)
                if held:
                    say(f"[{entry['label']}] {held} more matching line(s) were suppressed")

                text = line.strip()
                if len(text) > settings["maxLineLength"]:
                    text = text[: settings["maxLineLength"]] + " ..."

                say(f"[{entry['label']}] {text}")
                last_line[path] = line
                recent.append(now)
                window[path] = recent

        time.sleep(settings["pollSeconds"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
