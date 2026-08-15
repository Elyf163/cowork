---
name: cowork
description: >-
  Use when a Codex planning/review conversation must hand off project edits to
  one or more configured coding agents (OpenCode, Reasonix, Claude Code, a
  DeepSeek Harness adapter, or another CLI) with bounded rounds and a safe,
  cross-platform project boundary.
---

# Cowork

Codex is Planner/Reviewer. The selected agent is Executor. Codex may write
only `.cowork/**`; the Executor may write project source only. Keep the current
Codex task as the UI: no server, daemon, detached worker, or Codex CLI.

## First activation

If `.cowork/plan.md` has no `executor_policy`, stop and ask once:

```text
执行 agent（可多选）：codex-chat | opencode (recommended) | reasonix |
deepseek-harness (dsh) | claude-code | custom:<id>
```

Resolve each selected command before approval. Use its own configured model,
reasoning strength, credentials, and skills: never add `--model`, `--effort`,
`--variant`, or a model/profile override unless the user explicitly asks.
`codex-chat` means a separate Codex conversation and is a manual handoff, not
the current Planner silently editing source. `deepseek-harness`/`dsh` uses the
installed `dsh --profile headless` CLI when available; `dsh web` is an
interactive UI and is not the executor. Do not use `command -v dsh` as the
only check: the runner also searches `DSH_BIN`, `NVM_BIN`, common nvm bins, and
Windows npm shims. If all fail, provide an explicit argv command in
`.cowork/executors.json`.

Record the immutable selection, exact project root, mode, and five-round budget
in `.cowork/plan.md`. Then ask for one start approval: `开始` (network) or
`开始离线`. That approval binds the agent set, root, network mode, and budget
through completion or round 5. Do not ask again between ordinary rounds.

## Agent registry

Optional `.cowork/executors.json` uses argv arrays, never shell strings:

```json
{"agents":{"my-agent":{"command":["my-agent","--root","{root}","{prompt}"],"input":"argv","native":true}}}
```

Placeholders are `{root}`, `{prompt}`, and `{max_steps}`. `input` is `argv` or
`stdin`; `native:true` declares that the agent itself enforces the project
boundary on non-Linux hosts. Unknown agents, malformed commands, shell strings,
and missing executables fail closed. Built-ins are OpenCode, Reasonix, Claude
Code, `dsh` headless (`deepseek-harness`), plus manual `codex-chat`.

## Task protocol

For each round, Codex writes compact `.cowork/round-NN-tasks.jsonl` records:

```json
{"id":"t1","agent":"opencode","allowed_paths":["src"],"deps":[],"objective":"...","checks":["..."]}
```

Codex assigns one bounded task to one selected agent. Dependencies are a DAG;
overlapping paths require an explicit dependency and run sequentially. No
silent agent substitution or automatic retry. The runner sends a short JSON
envelope containing root, round, task id, request pointer, digest, paths, and
rules. The agent reads objective and checks from `.cowork` and
returns one short result with `status`, `changed`, `checks`, `blockers`, and
`next`; the runner appends a compact `round-NN-events.jsonl`, while full
terminal output stays in the round log for human review.

Run in the foreground (works with `python`/`py -3` on Windows):

```text
python <cowork-skill>/scripts/run_executor.py <project-root> NN --task t1
```

Use `--executor <id>` only for an explicitly approved override. Use
`--unsafe-fallback` only after explicit approval when the host has no verified
sandbox. Linux uses bubblewrap when available; non-Linux execution requires an
agent-native boundary unless that explicit fallback is approved. Offline mode
requires a platform network sandbox.

## Invariants and review

- Executor path is the canonical project root; reject root, traversal, and
  symlink escapes. `.cowork/**` and `.git/**` are read-only to Executor.
- Executor cannot commit, push, merge, reset, clean, checkout, or use
  worktrees. Git inspection is read-only. Runtime caches are not project edits.
- Codex reloads status/diff/untracked files and changed source after every
  task, writes a human-readable `round-NN-review.md`, and never repairs source.
- `APPROVED` ends the loop; `REQUEST_CHANGES` creates a new bounded task. An
  interrupt is recorded, never retried automatically, and stops the loop.
- Changing agent set, model override, root, network mode, unsafe fallback, or
  exceeding five rounds requires new approval.

Keep records small: reference `plan` and task ids/digests instead of repeating
history or absolute paths. Never trade the safety invariants for fewer tokens.
