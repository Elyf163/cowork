#!/usr/bin/env python3
"""Allow executor Git inspection while rejecting every other Git subcommand."""

import os
import sys


ALLOWED = {
    "cat-file", "diff", "grep", "log", "ls-files", "rev-list", "rev-parse",
    "show", "status",
}
OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def subcommand(arguments: list[str]) -> str | None:
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in OPTIONS_WITH_VALUE:
            index += 2
        elif argument.startswith("-"):
            index += 1
        else:
            return argument
    return None


command = subcommand(sys.argv[1:])
if command not in ALLOWED:
    print(f"cowork: git {command or ''} is disabled for executors", file=sys.stderr)
    raise SystemExit(126)
os.execv("/tmp/cowork-real-git", ["git", *sys.argv[1:]])
