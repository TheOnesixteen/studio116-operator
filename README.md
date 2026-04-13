# Studio 116 Operator

Phase 1.1 builds the foundation: a local Python CLI, SQLite task storage, SQLite scheduler locks, read-only health inspection, runtime logs, and inspectable artifacts.

Phase 2 first-slice work adds delegated dry-run preparation only. The Operator can prepare a worker packet, create a Codex worktree, record an intended worker command, and stop before launching any delegated worker.

`OPERATOR.md` is the master source of truth. `AGENTS.md` rules apply here: never auto-deploy, never expose secrets, use SQLite locks only, and keep the scheduler responsible for lock lifecycle.

## Scope

Included in Phase 1.1:

- Task intake, listing, showing, and status reporting.
- SQLite-backed tasks, runs, artifacts, events, worker executions, and locks.
- Read-only inspection of Caddy, `kairoke.service`, and Docker health.
- Operator/runtime log tailing only.

Included in the Phase 2 first slice:

- Delegated dry-run task preparation.
- Codex dry-run packet creation with an isolated writable worktree.
- Claude Code dry-run packet creation in read-only mode without a mutable worktree.
- SQLite locks for scheduler, worker, repo, worktree, and the single writable Codex lane.
- Intended worker command recording only.

Not included:

- Deployment.
- Service restarts or reloads.
- Live config mutation.
- Secret reads.
- Live delegated worker invocation.
- Parallel writable delegated Codex tasks.
- Claude Code file changes.
- Dashboards or webhooks.
- Automatic worktree cleanup or deletion.

## First Run

Run commands from the repo root:

```bash
scripts/operator status
scripts/operator health check
scripts/operator logs tail
```

Create and run the explicit health-check task:

```bash
scripts/operator task create --project vps --type health_check --title "Inspect Caddy, kairoke.service, and Docker health" --goal "Read-only inspection of Caddy, kairoke.service, and Docker health"
scripts/operator run next
scripts/operator tasks list
scripts/operator task show <task_id>
```

If `scripts/` is on `PATH` or the wrapper is symlinked, use the charter-facing form:

```bash
operator task create
operator tasks list
operator task show
operator run next
operator status
operator logs tail
operator health check
```

## Health-Check Results

The health check separates execution success from environment findings:

- `overall_status = ok`: inspection completed and all findings are healthy.
- `overall_status = warning`: inspection completed and warnings were found, with no hard failures. The task status is `done`.
- `overall_status = failed`: inspection could not complete correctly or a required check failed. The task status is `failed`.

Artifacts are written under `runtime/artifacts/` and include `overall_status`, `summary`, `key_findings`, and classified checks.

## Tests

```bash
python3 -m unittest discover -s tests
python3 -m compileall app tools tests
```

No external Python test dependency is required for Phase 1.1.

## Delegated Dry Run

Create a Codex dry-run task:

```bash
scripts/operator task create --project operator --type delegated --title "Docs dry run" --goal "Prepare a docs-only delegated dry run" --worker codex --delegation-mode dry_run
scripts/operator run next
scripts/operator task show <task_id>
```

Create a Claude Code read-only dry-run task:

```bash
scripts/operator task create --project operator --type delegated --title "Read-only review" --goal "Prepare a read-only review packet" --worker claude_code --delegation-mode dry_run --read-only
scripts/operator run next
scripts/operator task show <task_id>
```

Dry-run behavior:

- Codex gets a `runtime/worktrees/<task_id>/codex` worktree and a worker packet artifact.
- Claude Code gets a read-only worker packet artifact and no mutable worktree.
- `worker_executions` records the intended command with `dry_run: true` and `launched: false`.
- No worker process is launched.

## Live Codex Docs-Only Slice

Phase 2.1 allows one live delegated Codex task shape:

```bash
scripts/operator task create --project operator --type delegated --title "README docs update" --goal "Make a docs-only README.md change" --worker codex --delegation-mode live_codex_docs_only
scripts/operator run next
scripts/operator task show <task_id>
```

Guardrails:

- Target is `README.md` only.
- Codex runs in `runtime/worktrees/<task_id>/codex`, not the canonical checkout.
- Only one writable live Codex task can run at a time.
- Timeout is 10 minutes.
- No package installs, network-dependent work, hidden files, env files, deploy/config/system files, commits, merges, pushes, or worktree cleanup.
- Successful live Codex execution stops in `review`, not `done`.

Review actions:

```bash
scripts/operator task approve <task_id>
scripts/operator task reject <task_id>
```

Approval marks the task `done`; rejection marks it `canceled`. Both preserve the worktree.
