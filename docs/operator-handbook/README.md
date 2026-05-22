# Operator Handbook

This handbook is a concise operating guide for the Studio 116 Operator. `OPERATOR.md` remains the master source of truth; this file summarizes the current implemented system, partial/stubbed areas, and planned direction without changing app code, services, registry, policy, deployment, or runtime state.

## Current Scope

**Implemented**

- Local Python CLI entrypoint at `scripts/operator`.
- SQLite-backed task, run, artifact, event, worker execution, and lock storage.
- Read-only health checks for Caddy, `kairoke.service`, and Docker.
- Scheduler-owned SQLite lock lifecycle.
- Delegated dry-run worker packet generation.
- Live Codex review lanes with isolated worktrees, policy validation, and mandatory human approval before promotion.
- Project registry and policy validation commands.
- Plain-English and spec-file intake paths that normalize work into `StandardizedTask`.
- Task inbox, task show, project context display, runtime log tailing, and approve/reject review commands.

**Partial / Stubbed**

- Live writable lanes are intentionally narrow and policy-whitelisted.
- External project writes have preflight and dry-run worktree planning, but remain approval-bound.
- Sequential pipeline preview exists for planner-to-Codex flow, but still stops at review.
- Dashboard and webhook support are not part of the current runtime surface.

**Planned**

- Broader worker ecosystem coordination.
- Additional proven write lanes only after narrow smoke tests and policy updates.
- More durable dashboard/web intake surfaces.
- Continued cleanup of naming drift and review noise without changing smoke-proven behavior.

## Architecture

The Operator is a Python orchestration service and CLI around a small set of inspectable modules:

- `app/main.py`: CLI parsing and command dispatch.
- `app/router.py`: task creation helpers for supported delegation modes.
- `app/task_engine.py`: task lifecycle, worker packet creation, review promotion/rejection, and health task execution.
- `app/scheduler.py`: queued task execution and scheduler-owned lock orchestration.
- `app/policies.py`: allowed actions, blocked actions, live Codex target validation, and policy registry validation.
- `app/project_registry.py`: registered projects, write policy checks, and external write preflight.
- `app/db.py`, `schema.sql`: SQLite persistence.
- `app/artifact_store.py`: JSON/text artifact writes.
- `app/locks.py`: SQLite lock acquisition, heartbeat, and release.
- `adapters/*`: worker-specific command and execution wrappers.
- `tools/*`: bounded system, git, log, and inspection helpers.

The design favors simple files, clear artifacts, and resumable review over hidden automation.

## Services

**Implemented**

- The Operator CLI runs from the repository root.
- Health checks inspect known infrastructure without mutating it.
- Runtime logs can be tailed through the Operator.

**Operational context from `OPERATOR.md`**

- Droplet: `do.116.studio`.
- Known services: n8n Docker container, `kairoke.service`, Caddy, and deprecated `suno-api`.
- Credentials exist outside the repo and must not be copied, printed, or committed.

**Not implemented as autonomous actions**

- No service restarts.
- No deploys.
- No DNS, SSL, Caddy, env, or production config mutation.

## Scheduler And Execution

The scheduler selects a queued task, creates a run, acquires scheduler-owned locks, transitions the task through execution states, and then releases locks through context-managed cleanup.

Implemented lock types include scheduler, worker, repo, worktree, and delegated writer locks. Live Codex execution uses the single writable Codex lane, with a 10-minute timeout and isolated worktree.

The scheduler owns lock lifecycle. Workers do not own lock cleanup.

## Task Lifecycle

Task states are defined in `app/models.py`:

```text
draft -> queued -> planning -> ready -> running -> review -> done
```

Other supported states include `blocked`, `awaiting_approval`, `failed`, and `canceled`.

Live delegated Codex work stops in `review` after successful execution. It becomes `done` only after explicit approval. Rejection marks it `canceled`. Failures remain visible for inspection.

## Project Registry And Policy

**Implemented**

- `registry/projects.yaml` is the project source for known projects, repo paths, stacks, domains, services, allowed agents, deployment method, status, notes, and write policy.
- `registry/policies.yaml` defines allowed and blocked actions plus live Codex lane target lists and hardening rules.
- `scripts/operator projects validate` validates project registry shape.
- `scripts/operator policies validate` validates policy registry shape.
- External write preflight checks whether a project, worker, and lane are authorized before any worktree or worker launch.

**Important boundary**

Registry and policy files are control-plane files. They should only change in explicit policy work, not as a side effect of docs or implementation tasks.

## Review And Promotion

Live Codex write lanes use review-first promotion:

1. Preflight validates project, worker, mode, target paths, timeout, and write boundaries.
2. Codex works in an isolated runtime worktree.
3. Post-run validation checks changed files and lane-specific content rules.
4. The task stops in `review`.
5. `scripts/operator task approve <task_id>` validates and applies the patch to the canonical checkout without commit, merge, push, or deploy.
6. `scripts/operator task reject <task_id>` archives the rejected patch and restores only validated delegated worktree changes.

Approval artifacts include patch and summary files. Rejection artifacts preserve the rejected diff and discard summary.

## Worktrees And Artifacts

Delegated Codex work uses:

```text
runtime/worktrees/<task_id>/codex
runtime/artifacts/<task_id>/<run_id>/
```

Artifacts are part of the audit trail. Worker packets, preflight results, worker results, review summaries, approved patches, rollback patches, rejected patches, and discard summaries are preserved for inspection.

The canonical checkout must remain untouched until explicit approval.

## Runtime DB And State

SQLite is the persistence layer. The Operator stores tasks, runs, artifacts, events, worker executions, and locks in the runtime database. SQLite locks are the only supported lock mechanism.

The system is designed to be inspectable and resumable:

- Task state is visible through CLI commands.
- Artifacts are plain JSON or text.
- Review tasks remain pending until an explicit approve or reject command.
- Failed or stale work is surfaced by the task inbox.

## Operational Commands

Run from the repo root:

```bash
scripts/operator status
scripts/operator tasks inbox
scripts/operator tasks list
scripts/operator task show <task_id>
scripts/operator run next
scripts/operator health check
scripts/operator logs tail
scripts/operator projects list
scripts/operator projects show <slug>
scripts/operator projects validate
scripts/operator policies validate
scripts/operator task approve <task_id>
scripts/operator task reject <task_id>
```

Common test commands:

```bash
python3 -m unittest discover -s tests
python3 -m compileall app tools tests
```

## Troubleshooting

- Use `scripts/operator tasks inbox` first. It shows unresolved work, review tasks, failures, running heartbeat context, and active locks.
- Use `scripts/operator task show <task_id>` for artifacts, status, project context, and run details.
- For review tasks, approve or reject explicitly; successful live Codex work does not auto-promote.
- If approval fails, inspect stale-base or changed-file validation artifacts before retrying.
- If a delegated worktree contains unexpected files, stop and inspect; do not manually promote.
- If a command would deploy, restart a service, mutate config, read secrets, install packages, or use network-dependent work, it is outside current safe scope unless a future explicit phase allows it.

## Limitations And Roadmap

Current hard boundaries:

- No auto-deploy.
- No service restarts or reloads.
- No secret reads or secret exposure.
- No package installs.
- No network-dependent worker work in live Codex packets.
- No commits, merges, pushes, or worktree cleanup automation.
- No broad app writes unless a lane is explicitly proven and policy-whitelisted.

Roadmap direction:

- Keep expanding by small, smoke-proven lanes.
- Preserve human approval before canonical checkout mutation.
- Keep artifacts and state plain enough to audit.
- Prefer official APIs over brittle browser automation.
- Escalate uncertainty rather than bluffing through risky operations.
