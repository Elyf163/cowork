#!/usr/bin/env python3
"""Run one approved Cowork executor round in a project-scoped OS sandbox."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys


def executable(name: str, override: str | None = None) -> str:
    candidate = override or shutil.which(name)
    if not candidate and name == "reasonix":
        fallback = Path.home() / ".local/bin/reasonix"
        candidate = str(fallback) if fallback.is_file() else None
    if not candidate:
        raise SystemExit(f"missing executable: {name}")
    return str(Path(candidate).resolve())


def sandbox(args: argparse.Namespace, project: Path) -> list[str]:
    cmd = [
        executable("bwrap", args.bwrap_bin),
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
    ]
    if not args.network:
        cmd.append("--unshare-net")
    cmd += [
        "--ro-bind", "/", "/",
        "--tmpfs", "/tmp",
        "--proc", "/proc",
        "--dev", "/dev",
        "--bind", str(project), str(project),
        "--ro-bind", str(project / ".cowork"), str(project / ".cowork"),
    ]
    git = project / ".git"
    if git.exists():
        cmd += ["--ro-bind", str(git), str(git)]
    git_executable = shutil.which("git")
    if git_executable:
        git_executable = str(Path(git_executable).resolve())
        git_guard = str(Path(__file__).with_name("git_guard.py").resolve())
        cmd += [
            "--ro-bind", git_executable, "/tmp/cowork-real-git",
            "--ro-bind", git_guard, git_executable,
        ]
    cmd += ["--chdir", str(project), "--setenv", "GIT_OPTIONAL_LOCKS", "0"]
    return cmd


def executor_command(args: argparse.Namespace, project: Path, prompt: str) -> list[str]:
    cmd = sandbox(args, project)
    if args.executor == "opencode":
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        opencode_data = (data_home / "opencode").resolve()
        if opencode_data.is_dir():
            cmd += ["--bind", str(opencode_data), str(opencode_data)]
        cmd += [executable("opencode", args.opencode_bin), "run", "--auto", "--dir", str(project)]
        if args.model:
            cmd += ["--model", args.model]
        return cmd + [prompt]

    reasonix_home = Path(os.environ.get("REASONIX_HOME", Path.home() / ".reasonix")).resolve()
    if not reasonix_home.is_dir():
        raise SystemExit(f"missing Reasonix home: {reasonix_home}")
    cmd += ["--bind", str(reasonix_home), str(reasonix_home)]
    cmd += [
        executable("reasonix", args.reasonix_bin),
        "run",
        "--profile", "economy",
        "--auto",
        "--output-format", "text",
        "--max-steps", str(args.max_steps),
        "--dir", str(project),
    ]
    if args.model:
        cmd += ["--model", args.model]
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("round", type=int)
    parser.add_argument("--executor", choices=("opencode", "reasonix"), default="opencode")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--network", dest="network", action="store_true",
                      help="allow network access (default)")
    mode.add_argument("--offline", dest="network", action="store_false",
                      help="isolate the network; requires a local model")
    parser.set_defaults(network=True)
    parser.add_argument("--model", help="explicit executor model override")
    parser.add_argument("--max-steps", type=int, default=12,
                        help="Reasonix tool-step limit (ignored by OpenCode)")
    parser.add_argument("--opencode-bin")
    parser.add_argument("--reasonix-bin")
    parser.add_argument("--bwrap-bin")
    args = parser.parse_args()
    if args.round < 1 or args.max_steps < 1:
        parser.error("round and max-steps must be positive")
    return args


def main() -> int:
    args = parse_args()
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        raise SystemExit(f"project directory not found: {project}")
    cowork = project / ".cowork"
    request = cowork / f"round-{args.round:02d}-request.md"
    log = cowork / f"round-{args.round:02d}-terminal.log"
    if not request.is_file():
        raise SystemExit(f"request file not found: {request}")
    if log.exists():
        raise SystemExit(f"refusing to overwrite existing log: {log}")

    prompt = (
        f"You are the {args.executor} executor in an approval-gated Cowork round.\n"
        f"The exact project root is {project}. It is already the target project; "
        "do not create another directory named after it.\n"
        "Modify only project source files. Do not modify .cowork, Git metadata, "
        "or files outside the project. Do not commit, push, merge, reset, clean, "
        "checkout, or create worktrees.\n\n"
        + request.read_text(encoding="utf-8")
    )
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env["OPENCODE_PERMISSION"] = json.dumps({
        "edit": {"*": "allow", ".cowork/**": "deny"},
        "bash": {
            "*": "allow",
            "*git *": "deny",
            "*git status*": "allow",
            "*git diff*": "allow",
            "*git log*": "allow",
            "*git show*": "allow",
            "*git ls-files*": "allow",
            "*git rev-parse*": "allow",
        },
    })
    cmd = executor_command(args, project, prompt)

    with log.open("x", encoding="utf-8") as output:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                output.write(line)
                output.flush()
            return process.wait()
        except KeyboardInterrupt:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
            return 130


if __name__ == "__main__":
    sys.exit(main())
