# How To Add An Operator Project

`OPERATOR.md` remains the master source of truth. This guide explains the operational meaning of a registered project and the safe flow for onboarding one.

## Registered Projects

A registered Operator project is an explicit entry in the project registry that tells the Operator what the project is, where it lives, which agents may work on it, and what kind of writes are allowed.

Registration is not permission to mutate production. It is context plus policy. The Operator still applies lane checks, target-path restrictions, worker permissions, lock rules, review steps, and approval gates.

## Project Access Levels

### Observed / Read-Only Projects

Observed projects are visible to the Operator for inspection, planning, review, and diagnostics. They are useful when a project is important operational context but has not yet earned any write lane.

Use this state when:

- the repo or site is new to the Operator
- the project has no proven rollback path
- the data shape or deployment process is still being mapped
- you want agents to audit before changing anything

Allowed work should be limited to file inspection, log review, documentation, planning, and recommendations.

### Writable Projects

Writable projects have one or more explicit write lanes. A writable project should still be narrow: define which worker can write, which mode is allowed, and which paths are valid targets.

Writable does not mean broad autonomy. Live writes must remain isolated, reviewable, and approval-bound unless a future phase explicitly proves and documents a broader flow.

## Agent Permissions

`allowed_agents` defines which workers may participate in the project at all. For example, a project may allow `claude_code` to plan, `codex` to make scoped changes, and `gemini_cli` to review.

`allowed_write_agents` is stricter. It defines which workers may produce writable changes. A worker can be allowed to inspect a project without being allowed to write to it.

Keep these lists conservative:

- start with read-only agents
- add write agents only after a narrow smoke test
- remove write access when a project becomes unstable or unclear

## Target Path Restrictions

Every writable lane should define target paths. A worker packet must only modify the paths listed for that task, and post-run validation must reject unexpected changes.

Good target paths are narrow and inspectable:

```text
docs/operator-handbook/*.md
tests/test_*.py
app/policies.py
```

Avoid broad targets for early onboarding:

```text
**
app/**
/
```

Do not include env files, deployment files, service configs, secret locations, runtime databases, or production data paths in write targets.

## Lane Types

### `docs_only`

Use a docs-only lane for markdown updates. This is the safest first writable lane because it does not change runtime behavior.

Expected boundaries:

- markdown targets only
- no registry or policy edits
- no code changes
- no service changes
- no package installs
- no network-dependent work

### `tests_only`

Use a tests-only lane when the intended change is characterization or regression coverage.

Expected boundaries:

- test files only
- no app implementation changes
- no fixture rewrites outside the approved targets
- no broad generated output
- run the focused test command when practical

Tests-only work is useful before expanding write permissions because it records expected behavior without changing the application surface.

## Safe Onboarding Flow

1. Register the project as observed/read-only.
2. Document the repo path, owner context, stack, deploy method, domains, services, and known risks.
3. Run read-only inspection through approved agents.
4. Identify one narrow first lane, preferably `docs_only`.
5. Add explicit `allowed_agents`, then add `allowed_write_agents` only for the worker that will execute the lane.
6. Define target paths as narrowly as possible.
7. Run a smoke task in an isolated worktree.
8. Validate changed files and lane-specific content.
9. Stop in review and require explicit human approval before promotion.
10. Expand write scope only after the lane is proven and documented.

## Example Read-Only Trader Entry

This example shows the intended shape for an observed project. It is documentation only, not a registry edit.

```yaml
trader:
  name: Trader 116
  status: observed
  repo_path: /root/Projects/trader.116.studio
  stack:
    - static dashboards
    - node scripts
    - n8n workflows
  domains:
    - trader.116.studio
  services: []
  allowed_agents:
    - claude_code
    - codex
    - gemini_cli
    - shell_ops
  allowed_write_agents: []
  write_policy:
    writable: false
    lanes: []
    notes:
      - Read-only until repo state, rollback path, dashboard builders, and workflow deployment process are fully documented.
      - No production data deletion, service changes, deploys, env edits, or secret reads.
```

The first writable lane for this project should be a small docs-only task after the read-only audit is complete.
