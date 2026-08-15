#!/usr/bin/env python3
"""Run one bounded Cowork task with a configured coding agent."""

from __future__ import annotations

import argparse
import atexit
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Any


GIT_GUARD = Path(__file__).with_name("git_guard.py").resolve()
RUNTIME_DIRS: list[Path] = []


def cleanup_runtime() -> None:
    for path in RUNTIME_DIRS:
        shutil.rmtree(path, ignore_errors=True)
    RUNTIME_DIRS.clear()


atexit.register(cleanup_runtime)


DEFAULT_AGENTS: dict[str, dict[str, Any]] = {
    "opencode": {
        "command": ["opencode", "run", "--auto", "--dir", "{root}", "{prompt}"],
        "input": "argv", "native": True, "model_flag": "--model", "runtime": "opencode",
    },
    "reasonix": {
        "command": ["reasonix", "run", "--auto", "--output-format", "text",
                     "--max-steps", "{max_steps}", "--dir", "{root}"],
        "input": "stdin", "native": False, "model_flag": "--model", "runtime": "reasonix",
    },
    "claude-code": {
        "command": ["claude", "-p", "--permission-mode", "acceptEdits", "{prompt}"],
        "input": "argv", "native": False, "model_flag": "--model",
    },
    "deepseek-harness": {
        "command": ["dsh", "--profile", "headless", "{prompt}"],
        "input": "argv", "native": False, "runtime": "dsh",
    },
    "codex-chat": {
        "manual": True,
        "hint": "start a separate Codex conversation with the generated handoff",
    },
}

AGENT_ALIASES = {
    "dsh": "deepseek-harness",
    "deepseek": "deepseek-harness",
    "deepseek harness": "deepseek-harness",
}


def executable_candidates(name: str) -> list[Path]:
    """Find user-installed CLIs even when a package manager bin dir is not on PATH."""
    candidates: list[Path] = []
    env_name = name.upper().replace("-", "_") + "_BIN"
    if os.environ.get(env_name):
        candidates.append(Path(os.environ[env_name]).expanduser())
    if name == "reasonix":
        candidates.append(Path.home() / ".local/bin/reasonix")
    if name == "dsh":
        candidates.append(Path.home() / ".local/bin/dsh")
        nvm_bin = os.environ.get("NVM_BIN")
        if nvm_bin:
            candidates.append(Path(nvm_bin) / "dsh")
        nvm_root = Path.home() / ".nvm/versions/node"
        if nvm_root.is_dir():
            candidates.extend(path / "bin/dsh" for path in sorted(nvm_root.iterdir(), reverse=True))
        for base_name in ("APPDATA", "LOCALAPPDATA"):
            base = os.environ.get(base_name)
            if base:
                candidates.append(Path(base) / "npm" / "dsh.cmd")
    return candidates


def find_executable(name: str, override: str | None = None) -> str | None:
    candidate = override or shutil.which(name)
    if not candidate:
        candidate = next((str(path) for path in executable_candidates(name) if path.is_file()), None)
    return candidate


def executable(name: str, override: str | None = None) -> str:
    candidate = find_executable(name, override)
    if not candidate:
        raise SystemExit(f"missing executable: {name}")
    return str(Path(candidate).resolve())


def load_agents(project: Path) -> dict[str, dict[str, Any]]:
    agents = copy.deepcopy(DEFAULT_AGENTS)
    config = project / ".cowork" / "executors.json"
    if not config.is_file():
        return agents
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid executor registry: {config}") from exc
    configured = data.get("agents")
    if not isinstance(configured, dict):
        raise ValueError("executor registry 'agents' must be an object")
    for agent_id, spec in configured.items():
        if not isinstance(agent_id, str) or not isinstance(spec, dict):
            raise ValueError("executor registry entries must be objects")
        if not spec.get("manual") and not isinstance(spec.get("command"), list):
            raise ValueError(f"executor {agent_id!r} needs an argv command list")
        if spec.get("command") and any(not isinstance(part, str) for part in spec["command"]):
            raise ValueError(f"executor {agent_id!r} command must contain strings")
        if spec.get("input", "argv") not in {"argv", "stdin"}:
            raise ValueError(f"executor {agent_id!r} input must be argv or stdin")
        agents[agent_id] = {"id": agent_id, **spec}
    return agents


def canonical_agent_id(agent_id: Any, agents: dict[str, dict[str, Any]]) -> Any:
    if not isinstance(agent_id, str) or agent_id in agents:
        return agent_id
    alias = AGENT_ALIASES.get(agent_id.strip().lower())
    return alias if alias in agents else agent_id


def project_root(path: str | Path) -> Path:
    project = Path(path).expanduser().resolve()
    if not project.is_dir() or project.parent == project:
        raise ValueError(f"invalid project root: {project}")
    cowork = project / ".cowork"
    if not cowork.is_dir() or cowork.is_symlink():
        raise ValueError(f"project must contain a real .cowork directory: {cowork}")
    if (project / ".git").is_symlink():
        raise ValueError("project .git may not be a symlink")
    return project


def validate_task(project: Path, task: dict[str, Any], agents: dict[str, dict[str, Any]]) -> None:
    task_id = task.get("id")
    agent_id = canonical_agent_id(task.get("agent"), agents)
    task["agent"] = agent_id
    if not isinstance(task_id, str) or not task_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in task_id):
        raise ValueError("task id must be a short path-safe string")
    if agent_id not in agents:
        raise ValueError(f"unknown executor: {agent_id}")
    paths = task.get("allowed_paths", [])
    if not isinstance(paths, list) or not paths:
        raise ValueError(f"task {task_id} needs allowed_paths")
    for relative in paths:
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"task {task_id} has an unsafe path: {relative!r}")
        if relative == "." and task.get("legacy"):
            continue
        target = (project / relative).resolve()
        try:
            target.relative_to(project)
        except ValueError as exc:
            raise ValueError(f"task {task_id} escapes project root") from exc
        cursor = project
        for part in Path(relative).parts:
            cursor /= part
            if cursor.is_symlink():
                raise ValueError(f"task {task_id} may not target a symlink")
        if (target == project or target == project / ".cowork" or
                (project / ".cowork") in target.parents or target == project / ".git" or
                (project / ".git") in target.parents):
            raise ValueError(f"task {task_id} may not target .cowork or .git")


def validate_manifest(project: Path, tasks: list[dict[str, Any]], agents: dict[str, dict[str, Any]]) -> None:
    seen: set[str] = set()
    for task in tasks:
        validate_task(project, task, agents)
        if task["id"] in seen:
            raise ValueError(f"duplicate task id: {task['id']}")
        seen.add(task["id"])
        if not isinstance(task.get("deps", []), list) or any(dep not in seen and dep != task["id"] for dep in task.get("deps", [])):
            raise ValueError(f"task {task['id']} has an unknown or forward dependency")
    for index, left in enumerate(tasks):
        left_paths = [(project / path).resolve() for path in left["allowed_paths"] if path != "."]
        for right in tasks[index + 1:]:
            right_paths = [(project / path).resolve() for path in right["allowed_paths"] if path != "."]
            overlap = any(a == b or a in b.parents or b in a.parents for a in left_paths for b in right_paths)
            ordered = left["id"] in right.get("deps", []) or right["id"] in left.get("deps", [])
            if overlap and not ordered:
                raise ValueError(f"overlapping task paths need a dependency: {left['id']}, {right['id']}")


def read_tasks(cowork: Path, round_number: int) -> list[dict[str, Any]]:
    path = cowork / f"round-{round_number:02d}-tasks.jsonl"
    if path.is_file():
        tasks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not all(isinstance(task, dict) for task in tasks):
            raise ValueError(f"invalid task manifest: {path}")
        return tasks
    request = cowork / f"round-{round_number:02d}-request.md"
    if not request.is_file():
        raise ValueError(f"task manifest not found: {path}")
    return [{"id": f"round-{round_number:02d}", "agent": "opencode", "legacy": True,
             "request": f".cowork/round-{round_number:02d}-request.md",
             "allowed_paths": ["."], "objective": request.read_text(encoding="utf-8"),
             "checks": []}]


def task_envelope(project: Path, round_number: int, task: dict[str, Any], digest: str) -> str:
    payload = {
        "v": 1, "root": str(project), "round": round_number, "task": task["id"],
        "request": task.get("request", f".cowork/round-{round_number:02d}-tasks.jsonl#{task['id']}"),
        "plan": digest, "agent": task["agent"], "paths": task["allowed_paths"],
        "rules": "read request; edit project source only; .cowork and Git state are read-only; no retry",
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def render_agent_command(spec: dict[str, Any], project: Path, envelope: str,
                         explicit_model: str | None = None,
                         max_steps: int = 12) -> tuple[list[str], str | None]:
    if spec.get("manual"):
        raise ValueError(spec.get("hint", "manual executor requires a separate handoff"))
    command = spec.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError("executor command must be a non-empty argv list")
    values = {"root": str(project), "prompt": envelope, "max_steps": str(max_steps)}
    try:
        rendered = [part.format(**values) for part in command]
    except KeyError as exc:
        raise ValueError(f"unknown executor placeholder: {exc.args[0]}") from exc
    if explicit_model:
        flag = spec.get("model_flag")
        if not isinstance(flag, str) or not flag:
            raise ValueError("this executor has no declared model override flag")
        insertion = rendered.index(envelope) if envelope in rendered else len(rendered)
        rendered[insertion:insertion] = [flag, explicit_model]
    if spec.get("input", "argv") == "stdin":
        return rendered, envelope
    return rendered, None


def resolve_argv(command: list[str], override: str | None = None) -> list[str]:
    first = command[0]
    found = find_executable(first, override)
    if not found:
        raise SystemExit(f"missing executable: {first}")
    command = [str(Path(found).resolve()), *command[1:]]
    if os.name == "nt" and Path(command[0]).suffix.lower() in {".cmd", ".bat"}:
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/d", "/s", "/c", subprocess.list2cmdline(command)]
    return command


def linux_sandbox(command: list[str], project: Path, args: argparse.Namespace,
                  agent: dict[str, Any]) -> list[str] | None:
    if not sys.platform.startswith("linux") or not shutil.which("bwrap"):
        return None
    bwrap = executable("bwrap", args.bwrap_bin)
    wrapped = [bwrap, "--die-with-parent", "--new-session", "--unshare-pid",
               "--unshare-ipc", "--unshare-uts"]
    if not args.network:
        wrapped.append("--unshare-net")
    wrapped += ["--ro-bind", "/", "/", "--tmpfs", "/tmp", "--proc", "/proc",
                "--dev", "/dev", "--bind", str(project), str(project),
                "--ro-bind", str(project / ".cowork"), str(project / ".cowork")]
    git = project / ".git"
    if git.exists():
        wrapped += ["--ro-bind", str(git), str(git)]
    git_executable = shutil.which("git")
    if git_executable and GIT_GUARD.is_file():
        real_git = str(Path(git_executable).resolve())
        wrapped += ["--ro-bind", real_git, "/tmp/cowork-real-git",
                    "--ro-bind", str(GIT_GUARD), real_git]
    runtime_name = agent.get("runtime")
    if runtime_name:
        if runtime_name == "opencode":
            source = (Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "opencode").resolve()
            target = source
        elif runtime_name == "reasonix":
            source = Path(os.environ.get("REASONIX_HOME", Path.home() / ".reasonix")).resolve()
            target = source
        elif runtime_name == "dsh":
            source = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh")).expanduser().resolve()
            target = source
        else:
            source = Path(str(runtime_name)).expanduser().resolve()
            target = source
        if source.is_dir() or runtime_name == "dsh":
            runtime = Path(tempfile.mkdtemp(prefix="cowork-runtime-"))
            if source.is_dir():
                shutil.copytree(source, runtime, dirs_exist_ok=True)
            RUNTIME_DIRS.append(runtime)
            if not source.is_dir():
                wrapped += ["--dir", str(target)]
            wrapped += ["--bind", str(runtime), str(target)]
    return wrapped + ["--chdir", str(project), "--setenv", "GIT_OPTIONAL_LOCKS", "0", *command]


def command_for_platform(command: list[str], project: Path, args: argparse.Namespace,
                         agent: dict[str, Any]) -> list[str]:
    wrapped = linux_sandbox(command, project, args, agent)
    if wrapped:
        return wrapped
    if not agent.get("native", False) and not args.unsafe_fallback:
        raise ValueError("no verified sandbox for this executor on this platform; use an agent with native policy or explicit --unsafe-fallback")
    if not args.network:
        raise ValueError("offline mode needs a platform network sandbox")
    return command


def terminate(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except (AttributeError, OSError):
            process.terminate()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("round", type=int)
    parser.add_argument("--task")
    parser.add_argument("--executor")
    parser.add_argument("--network", dest="network", action="store_true")
    parser.add_argument("--offline", dest="network", action="store_false")
    parser.set_defaults(network=True)
    parser.add_argument("--model", help="explicit model override; omitted by default")
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--unsafe-fallback", action="store_true")
    parser.add_argument("--opencode-bin")
    parser.add_argument("--reasonix-bin")
    parser.add_argument("--dsh-bin")
    parser.add_argument("--bwrap-bin")
    args = parser.parse_args()
    if args.round < 1 or args.round > 5 or args.max_steps < 1:
        parser.error("round must be between 1 and 5 and max-steps must be positive")
    return args


def main() -> int:
    args = parse_args()
    try:
        project = project_root(args.project)
        agents = load_agents(project)
        tasks = read_tasks(project / ".cowork", args.round)
        validate_manifest(project, tasks, agents)
        task = next((item for item in tasks if not args.task or item["id"] == args.task), None)
        if task is None:
            raise ValueError(f"task not found: {args.task}")
        if args.executor:
            task = {**task, "agent": args.executor}
            validate_task(project, task, agents)
        agent = agents[task["agent"]]
        plan = project / ".cowork" / "plan.md"
        digest = "sha256:" + hashlib.sha256(plan.read_bytes() if plan.is_file() else b"").hexdigest()[:16]
        envelope = task_envelope(project, args.round, task, digest)
        if agent.get("manual"):
            handoff = project / ".cowork" / f"round-{args.round:02d}-{task['id']}-handoff.json"
            handoff.write_text(json.dumps({"envelope": json.loads(envelope),
                                           "hint": agent.get("hint", "manual handoff")},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"manual executor: read {handoff} in the selected agent conversation")
            return 3
        command, input_text = render_agent_command(agent, project, envelope, args.model, args.max_steps)
        override = (args.opencode_bin if task["agent"] == "opencode" else
                    args.reasonix_bin if task["agent"] == "reasonix" else
                    args.dsh_bin if task["agent"] == "deepseek-harness" else None)
        command = command_for_platform(resolve_argv(command, override), project, args, agent)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc

    task_id = task["id"]
    log = project / ".cowork" / f"round-{args.round:02d}-{task_id}-terminal.log"
    if log.exists():
        raise SystemExit(f"refusing to overwrite existing log: {log}")
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env["COWORK_REAL_GIT"] = "/tmp/cowork-real-git"
    for name in ("GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS", "GIT_PAGER", "GIT_EDITOR",
                 "GIT_SSH_COMMAND", "GIT_SEQUENCE_EDITOR"):
        env.pop(name, None)
    if os.name != "nt":
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        for name in list(env):
            if name.startswith("GIT_CONFIG_KEY_") or name.startswith("GIT_CONFIG_VALUE_"):
                env.pop(name, None)
        env.pop("GIT_CONFIG_COUNT", None)
    env["OPENCODE_PERMISSION"] = json.dumps({
        "edit": {"*": "allow", ".cowork/**": "deny"},
        "bash": {"*": "allow", "*git *": "deny", "*git status*": "allow",
                  "*git diff*": "allow", "*git log*": "allow", "*git show*": "allow",
                  "*git ls-files*": "allow", "*git rev-parse*": "allow"},
    })
    popen: dict[str, Any] = {"cwd": str(project), "stdout": subprocess.PIPE,
                             "stderr": subprocess.STDOUT, "text": True,
                             "encoding": "utf-8", "errors": "replace", "env": env}
    if os.name == "nt":
        popen["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen["start_new_session"] = True
    status = "completed"
    exit_code = 1
    process: subprocess.Popen[str] | None = None
    try:
        with log.open("x", encoding="utf-8") as output:
            process = subprocess.Popen(command, stdin=subprocess.PIPE if input_text else subprocess.DEVNULL, **popen)
            assert process.stdout is not None
            if input_text and process.stdin is not None:
                process.stdin.write(input_text)
                process.stdin.close()
            for line in process.stdout:
                print(line, end="", flush=True)
                output.write(line)
                output.flush()
            exit_code = process.wait()
    except KeyboardInterrupt:
        status = "interrupted"
        if process is not None:
            terminate(process)
        exit_code = 130
    finally:
        event = {"v": 1, "round": args.round, "task": task_id, "agent": task["agent"],
                 "status": status if status == "interrupted" else ("ok" if exit_code == 0 else "failed"),
                 "exit": exit_code, "log": log.name}
        with (project / ".cowork" / f"round-{args.round:02d}-events.jsonl").open("a", encoding="utf-8") as events:
            events.write(json.dumps(event, separators=(",", ":")) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
