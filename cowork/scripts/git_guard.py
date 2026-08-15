#!/usr/bin/env python3
"""Allow executor Git inspection while rejecting every other Git subcommand."""

import os
import sys


ALLOWED = {
    "cat-file", "diff", "grep", "log", "ls-files", "rev-list", "rev-parse",
    "show", "status",
}
OPTIONS_WITH_VALUE = {"-C", "--git-dir", "--work-tree", "--namespace"}
BLOCKED_OPTIONS = {"-c", "--config-env", "--config-system", "--config-global",
                   "--config-local", "--exec-path"}


def subcommand(arguments: list[str]) -> str | None:
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in BLOCKED_OPTIONS or argument.startswith("--config-") or (argument.startswith("-c") and argument != "--"):
            return None
        if argument in OPTIONS_WITH_VALUE:
            index += 2
        elif argument.startswith("-"):
            index += 1
        else:
            return argument
    return None


arguments = sys.argv[1:]
command = subcommand(arguments)
blocked_env = ("GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS", "GIT_PAGER", "GIT_EDITOR",
               "GIT_SSH_COMMAND", "GIT_SEQUENCE_EDITOR")
blocked = any(os.environ.get(name) for name in blocked_env)
blocked |= command == "diff" and any(arg == "--output" or arg.startswith("--output=") or
                                     arg in {"--ext-diff", "--textconv"} for arg in arguments)
if blocked or command not in ALLOWED:
    print(f"cowork: git {command or ''} is disabled for executors", file=sys.stderr)
    raise SystemExit(126)
os.execv(os.environ.get("COWORK_REAL_GIT", "/tmp/cowork-real-git"), ["git", *arguments])
