# Studio 116 Operator

Phase 1.1 builds the foundation only: a local Python CLI, SQLite task storage, SQLite scheduler locks, read-only health inspection, runtime logs, and inspectable artifacts.

`OPERATOR.md` is the master source of truth. `AGENTS.md` rules apply here: never auto-deploy, never expose secrets, use SQLite locks only, and keep the scheduler responsible for lock lifecycle.

## Scope

Included in Phase 1.1:

- Task intake, listing, showing, and status reporting.
- SQLite-backed tasks, runs, artifacts, events, worker executions, and locks.
- Read-only inspection of Caddy, `kairoke.service`, and Docker health.
- Operator/runtime log tailing only.

Not included in Phase 1.1:

- Deployment.
- Service restarts or reloads.
- Live config mutation.
- Secret reads.
- AI worker delegation.
- Dashboards or webhooks.

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
