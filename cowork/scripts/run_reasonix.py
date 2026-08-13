#!/usr/bin/env python3
"""Run one approved Reasonix round in a project-scoped OS sandbox."""

from __future__ import annotations

import argparse
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


def command(args: argparse.Namespace, project: Path, request: Path) -> list[str]:
    reasonix = executable("reasonix", args.reasonix_bin)
    bwrap = executable("bwrap", args.bwrap_bin)
    reasonix_home = Path(os.environ.get("REASONIX_HOME", Path.home() / ".reasonix")).resolve()
    if not reasonix_home.is_dir():
        raise SystemExit(f"missing Reasonix home: {reasonix_home}")

    cmd = [
        bwrap,
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
        "--bind", str(reasonix_home), str(reasonix_home),
        "--ro-bind", str(project / ".cowork"), str(project / ".cowork"),
    ]
    git = project / ".git"
    if git.exists():
        cmd += ["--ro-bind", str(git), str(git)]
    cmd += [
        "--chdir", str(project),
        "--setenv", "GIT_OPTIONAL_LOCKS", "0",
        reasonix,
        "run",
        "--profile", "economy",
        "--auto",
        "--output-format", "text",
        "--max-steps", str(args.max_steps),
        "--dir", str(project),
    ]
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("round", type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--network", dest="network", action="store_true",
                      help="allow network access (default)")
    mode.add_argument("--offline", dest="network", action="store_false",
                      help="isolate the network; requires a local model")
    parser.set_defaults(network=True)
    parser.add_argument("--max-steps", type=int, default=12)
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
        "You are the Reasonix executor in an approval-gated Cowork round.\n"
        f"The exact project root is {project}. It is already the target project; "
        "do not create another directory named after it.\n"
        "Modify only project source files. Do not modify .cowork, Git metadata, "
        "or files outside the project. Do not commit, push, merge, reset, clean, "
        "checkout, or create worktrees.\n\n"
        + request.read_text(encoding="utf-8")
    )
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    cmd = command(args, project, request)

    with log.open("x", encoding="utf-8") as output:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(prompt)
        process.stdin.close()
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
