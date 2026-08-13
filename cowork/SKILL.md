---
name: cowork
description: >-
  Orchestrate a single-approval coding loop in the current Codex desktop task:
  Codex plans and reviews in chat, OpenCode (default) or Reasonix executes in
  the built-in terminal, and project-local .cowork files record each round.
  Use for Cowork requests or planner/executor/reviewer loops that run
  automatically after one user-approved start mode.
---

# Cowork

Use the current Codex desktop task as the only UI. Do not start Chainlit,
LangGraph, Codex CLI, a web server, or a detached worker.

## Roles

- Codex: inspect read-only, plan, prepare executor instructions, refresh state,
  review, and report in the current chat. Codex may write only `.cowork/**` and
  must never repair target project source itself.
- Executor: OpenCode is recommended and used by default; Reasonix remains
  available when the user explicitly selects it. It may modify project source
  only after one explicit approval starts the complete loop. It must never
  modify `.cowork/**`, files outside the exact project root, or Git state.
- User: may interrupt at any time and may add feedback while the loop is active.

Default to OpenCode, five executor rounds, and network access. Preserve the
user's existing executor configuration and model. In particular, never select,
override, or hardcode an OpenCode model, and do not pass `--model` unless the
user explicitly requested that model for this Cowork run. An explicitly
selected executor, model, or offline mode applies to the complete loop. Raising
the limit or changing those choices requires explicit user input.

## Project protocol

Resolve the project root once. The directory passed to the executor is the exact
project root; never repeat an absolute user path as a nested directory.

Keep the transparent record here:

```text
.cowork/
├── plan.md
├── round-01-request.md
├── round-01-terminal.log
└── round-01-review.md
```

Add the same three round files for later rounds. Do not add a database, daemon,
state machine, or second UI.

## 1. Plan

1. Inspect the current project without changing source files.
2. Resolve every requested Codex or executor skill before proposing execution.
   Record its exact `SKILL.md` path. If unavailable, tell the user now; never
   let the executor spend a round searching for or installing it.
3. Prefer the standard library, platform features, and installed dependencies.
   If the round will be offline, do not plan a dependency download.
4. Write `.cowork/plan.md` with the task, exact root, constraints, concise plan,
   acceptance checks, selected executor, any explicitly requested model,
   selected skills, and five-round limit.
5. Show the complete plan in the current Codex response.
6. End the turn with one start choice: `开始` (network, the default) or
   `开始离线`. Explain that offline works only with an executor configuration
   that needs no network. This single approval authorizes the automatic loop
   through completion or the round limit. Do not request approval again between
   normal rounds.

## 2. Run the approved loop

After the single start approval, repeat the following steps until approved,
interrupted, blocked by a permission boundary, or the round limit is reached.
Before each new round, incorporate any user feedback that arrived in the
current Codex task.

Create the next `round-NN-request.md`. Include:

- exact project root and the statement that it is already the project root;
- original task and approved plan;
- prior Codex findings and new user feedback;
- exact executor skill path, if selected;
- a small, bounded objective for this round;
- prohibitions on writing outside the root and on `git commit`, `push`,
  `merge`, `reset`, `clean`, `checkout`, and worktree operations;
- required minimal checks and a concise final report.

Run the selected executor in the foreground through the built-in terminal:

```bash
python3 <cowork-skill>/scripts/run_executor.py /absolute/project/root NN
```

This uses OpenCode by default. Add `--executor reasonix` only when Reasonix was
selected. Add `--model <provider/model>` only when the user explicitly requested
that model; otherwise omit it so OpenCode uses the user's existing configuration
and current model.

Add `--offline` only when the loop was explicitly started with `开始离线`.
`--network` remains accepted for compatibility but network is the default.
Keep the selected executor, model policy, and mode fixed for all rounds. The
runner streams output to the terminal, records it in `.cowork`, makes the rest
of the host filesystem read-only, keeps `.cowork` and Git metadata read-only to
the executor, and limits Git to read-only inspection commands inside the
executor sandbox. The Reasonix backend defaults to 12 tool steps. Never detach
the command. The Codex Stop control is the hard interrupt.

## 3. Refresh and review

Immediately after the executor exits or is interrupted:

1. Reload `git status`, `git diff`, untracked files, and every changed source
   file from disk. For a non-Git project, list and read the project files.
2. Treat the filesystem as truth; do not review only the executor's summary.
3. Check the approved task, scope, correctness, and smallest relevant tests.
   Codex must not repair source code itself.
4. Recheck status just before publishing the verdict. If files changed during
   review, discard the verdict and review the new state.
5. Write `round-NN-review.md` with `APPROVED` or `REQUEST_CHANGES`, findings,
   checks observed, and the next bounded objective.
6. Show the full review in the current Codex task. During an active loop, use a
   concise progress update so the user can observe and interrupt before the
   next terminal command.

For `REQUEST_CHANGES`, immediately prepare and run the next bounded round
without asking for another offline/network approval. For `APPROVED`, report the
result and leave committing, merging, or deleting to an explicit user request.

Pause and request new approval only when the next action would:

- change an offline loop to network access;
- change the selected executor or add/change a model override;
- expand the writable project root or use a new external permission;
- perform a destructive or irreversible action; or
- exceed the configured round limit.

Do not turn ordinary code-review findings into approval prompts.

## Interrupted runs

After an interrupt, never auto-retry. Refresh the filesystem, report residual
changes, write the review, and stop the loop. The user decides whether to start
again.
