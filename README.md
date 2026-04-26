# Studio 116 Operator

Phase 1.1 builds the foundation: a local Python CLI, SQLite task storage, SQLite scheduler locks, read-only health inspection, runtime logs, and inspectable artifacts.

Phase 2 first-slice work adds delegated dry-run preparation only. The Operator can prepare a worker packet, create a Codex worktree, record an intended worker command, and stop before launching any delegated worker.

Phase 2.2 closes the proven live Codex docs-only review-and-approval loop for the Operator repo only. Approval promotes a validated `README.md` patch into the canonical working tree without committing, merging, or pushing. Rejection archives and discards only the delegated worktree's `README.md` change.

Phase 2.3 keeps the same live Codex review loop and replaces the hardcoded `README.md` target with a policy-backed docs whitelist. The active whitelist lives in `registry/policies.yaml` and allows `README.md`, `OPERATOR.md`, and `AGENTS.md`.

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

Included in the Phase 2.2 review loop:

- Explicit human-triggered approval promotion for `live_codex_docs_only` review tasks.
- `README.md` only, Operator repo only, Codex only.
- Promotion preflight with `git apply --check` against the canonical checkout to block stale-base patches.
- Preserved `approved_patch.patch`, `rollback_patch.patch`, and `promotion_summary.json`.
- Explicit rejection that archives `rejected_patch.patch` and discards only the delegated worktree's `README.md` change.
- Preserved worktrees and artifacts.

Included in the Phase 2.3 docs whitelist:

- Policy-backed live Codex docs targets from `registry/policies.yaml`.
- Active allowed targets: `README.md`, `OPERATOR.md`, and `AGENTS.md`.
- `README.md` remains the default target when no `--target-path` is supplied.
- Every requested target and every changed file must be policy-allowed before launch, after run, and during approve/reject.
- Rejection restores each validated changed docs file in the delegated worktree.

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
- Commits, merges, or pushes from approval.
- Any live Codex target outside the active docs whitelist.
- `docs/*.md` activation.

## First Run

Run commands from the repo root:

```bash
scripts/operator status
scripts/operator tasks inbox
scripts/operator health check
scripts/operator logs tail
```

Create and run the explicit health-check task:

```bash
scripts/operator task create --project vps --type health_check --title "Inspect Caddy, kairoke.service, and Docker health" --goal "Read-only inspection of Caddy, kairoke.service, and Docker health"
scripts/operator run next
scripts/operator tasks inbox
scripts/operator tasks list
scripts/operator task show <task_id>
```

If `scripts/` is on `PATH` or the wrapper is symlinked, use the charter-facing form:

```bash
operator task create
operator tasks list
operator task show
operator run next
operator tasks inbox
operator status
operator logs tail
operator health check
```

## Daily Task Inbox

Use the read-only task inbox when starting work or checking what needs attention:

```bash
scripts/operator tasks inbox
```

The inbox shows task counts, review items that need approve/reject attention, failed task summaries, running task heartbeat context, queued tasks, and active lock summaries. It does not mutate tasks, clean locks, approve or reject work, or print raw worker stdout/stderr.

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

Select another whitelisted docs target explicitly:

```bash
scripts/operator task create --project operator --type delegated --title "Operator docs update" --goal "Make a docs-only OPERATOR.md change" --worker codex --delegation-mode live_codex_docs_only --target-path OPERATOR.md
```

Multiple whitelisted docs targets are allowed up to the 5-file ceiling:

```bash
scripts/operator task create --project operator --type delegated --title "Docs wording update" --goal "Make docs-only wording changes" --worker codex --delegation-mode live_codex_docs_only --target-path README.md --target-path AGENTS.md
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

Approval re-checks the delegated worktree diff, requires policy-whitelisted docs files only, writes `promotion_preflight.json`, `approved_patch.patch`, `rollback_patch.patch`, and `promotion_summary.json`, then applies the approved patch to the canonical working tree without commit, merge, or push. Successful approval marks the task `done`.

Rejection writes `rejected_patch.patch`, discards only the validated delegated worktree docs changes, writes `discard_summary.json`, and marks the task `canceled`.

Failed approval or discard attempts leave the task in `review` and record failure artifacts/events. Worktrees and artifacts are preserved.
