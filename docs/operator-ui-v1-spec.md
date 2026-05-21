# Operator UI v1 Frontend Architecture Specification

## 1. API Contract

The UI is a Flask-rendered interface backed by JSON API endpoints. The frontend stack is locked to Flask templates, locally vendored htmx, vanilla JavaScript, and plain CSS. No React, CDN, npm, or network-dependent runtime assets are allowed.

All JSON responses include:

- `ok` required boolean: whether the request succeeded.
- `error` optional object: present only when `ok` is false.
- `error.code` required string when `error` is present.
- `error.message` required string when `error` is present.

### 1.1 `GET /api/inbox`

Maps to `task_engine.task_inbox()`.

Purpose: return tasks that need human review, ordered by urgency and creation time.

Request:

- No body.
- Query parameters:
  - `project` optional string.
  - `limit` optional integer, default `50`.
  - `cursor` optional string for pagination.

Response:

- `ok` required boolean.
- `tasks` required array of inbox task objects.
- `next_cursor` optional string.

Inbox task object:

- `task_id` required string.
- `run_id` optional string.
- `title` required string.
- `project` required string.
- `status` required string, expected `review`.
- `risk_level` required string: `low`, `medium`, or `high`.
- `pipeline` required string.
- `created_at` required ISO-8601 string.
- `updated_at` required ISO-8601 string.
- `summary` optional string.
- `changed_file_count` optional integer.
- `test_status` optional string: `passed`, `failed`, `not_run`, or `unknown`.
- `approve_url` required string.

### 1.2 `GET /api/tasks/{id}`

Maps to `task_engine.show_task(task_id)`.

Purpose: return canonical task metadata and lifecycle state.

Request:

- Path parameter `id` required string.
- No body.

Response:

- `ok` required boolean.
- `task` required object.

Task object:

- `task_id` required string.
- `title` required string.
- `project` required string.
- `status` required string.
- `risk_level` required string.
- `pipeline` optional string.
- `worker` optional string.
- `created_at` required ISO-8601 string.
- `updated_at` required ISO-8601 string.
- `worktree_path` optional string.
- `artifact_dir` optional string.
- `latest_run_id` optional string.
- `events` optional array of lifecycle event objects.

Lifecycle event object:

- `event_id` required string.
- `type` required string.
- `created_at` required ISO-8601 string.
- `message` optional string.
- `metadata` optional object.

### 1.3 `GET /api/tasks/{id}/review-packet`

Maps to a UI assembler over task artifacts:

- `worker_packet.json`
- `agent1_result.json`
- `git_diff.patch`
- `changed_files.json`
- `review_summary.json`
- snapshot of `registry/projects.yaml` state captured at task creation time

Purpose: return the normalized review packet used by the Review Packet screen. This is the primary approval endpoint and must be the first contract implemented.

Request:

- Path parameter `id` required string.
- No body.

Response:

- `ok` required boolean.
- `review_packet` required object matching the Review Packet Schema in section 3.

Failure response cases:

- `not_found`: task does not exist.
- `packet_unavailable`: artifacts have not been produced yet.
- `packet_invalid`: artifacts exist but cannot be normalized.

### 1.4 `POST /api/tasks/{id}/approve`

Maps to `task_engine.approve_task(task_id)`.

Purpose: approve a reviewed task for the next lifecycle transition. Approval does not deploy production changes.

Request:

- Path parameter `id` required string.
- Header or form CSRF token required.
- JSON body:
  - `confirm_token` required string.
  - `rollback_acknowledged` required boolean.
  - `friction_level` required string: `low`, `medium`, or `high`.
  - `read_receipt` optional object.

`read_receipt` object:

- `diff_scrolled_to_bottom` optional boolean.
- `expanded_files` optional array of strings.
- `raw_diff_opened` optional boolean.
- `confirmed_phrase` optional string.

Response:

- `ok` required boolean.
- `task_id` required string.
- `status` required string.
- `event_id` optional string.
- `message` required string.

### 1.5 `POST /api/tasks/{id}/reject`

Maps to `task_engine.reject_task(task_id)`.

Purpose: reject a reviewed task and record the reason for auditability.

Request:

- Path parameter `id` required string.
- Header or form CSRF token required.
- JSON body:
  - `reason` required string.
  - `details` optional string.
  - `rollback_acknowledged` required boolean.

Response:

- `ok` required boolean.
- `task_id` required string.
- `status` required string.
- `event_id` optional string.
- `message` required string.

### 1.6 `GET /api/tasks/{id}/diff`

Maps to serving the `git_diff.patch` artifact as text.

Purpose: expose the raw unified diff for inspection and download-like viewing in the browser. Raw diff is available but is not the default mobile review view.

Request:

- Path parameter `id` required string.
- Query parameter `format` optional string, default `text`; allowed values `text` and `json`.

Text response:

- Content type `text/plain; charset=utf-8`.
- Body is the unified diff string.

JSON response:

- `ok` required boolean.
- `task_id` required string.
- `raw_diff` required string.

### 1.7 `GET /api/queue`

Maps to `task_engine.list_tasks()` filtered to active states, enriched with lock information from `task_engine.active_locks()`.

Purpose: show what is running, queued, blocked, or waiting on locks.

Request:

- No body.
- Query parameters:
  - `project` optional string.
  - `include_done` optional boolean, default `false`.

Response:

- `ok` required boolean.
- `tasks` required array of queue task objects.
- `locks` required array of lock objects.

Queue task object:

- `task_id` required string.
- `title` required string.
- `project` required string.
- `status` required string.
- `worker` optional string.
- `pipeline` optional string.
- `created_at` required ISO-8601 string.
- `updated_at` required ISO-8601 string.
- `lock_id` optional string.
- `blocked_by_lock_id` optional string.
- `blocked_reason` optional string.

Lock object:

- `lock_id` required string.
- `scope` required string.
- `owner_task_id` required string.
- `worker` optional string.
- `acquired_at` required ISO-8601 string.
- `expires_at` optional ISO-8601 string.
- `status` required string: `active`, `stale`, or `releasing`.

### 1.8 `GET /api/brain/{project}`

Maps to reading `registry/projects.yaml` and `registry/workers.yaml`.

Purpose: show what the Operator knows about a project and which workers are available to act on it.

Request:

- Path parameter `project` required string.
- No body.

Response:

- `ok` required boolean.
- `project` required object.
- `workers` required array of worker objects.
- `snapshot_created_at` optional ISO-8601 string.

Project object:

- `id` required string.
- `name` required string.
- `type` optional string.
- `description` optional string.
- `repo` optional string.
- `deploy_policy` optional string.
- `known_paths` optional array of strings.
- `notes` optional array of strings.

Worker object:

- `id` required string.
- `role` required string.
- `capabilities` optional array of strings.
- `allowed_projects` optional array of strings.
- `constraints` optional array of strings.

### 1.9 `POST /api/tasks`

Maps to `task_engine.create_task()`.

Purpose: submit the Command Form and create a new task with a captured brain snapshot.

Request:

- Header or form CSRF token required.
- JSON body:
  - `title` required string.
  - `project` required string.
  - `goal` required string.
  - `mode` optional string, default determined by policy.
  - `pipeline` optional string.
  - `target_paths` optional array of strings.
  - `risk_level` optional string, default policy-derived.
  - `constraints` optional array of strings.
  - `approval_required` optional boolean, default `true` for reviewable work.
  - `brain_snapshot` required object captured from `registry/projects.yaml` at creation time.

Response:

- `ok` required boolean.
- `task_id` required string.
- `status` required string.
- `created_at` required ISO-8601 string.
- `review_url` optional string.
- `queue_url` required string.

### 1.10 `POST /api/tasks/preview`

Maps to the same policy and normalization path used before `task_engine.create_task()`, without persistence.

Purpose: power the Command Form preview so the user can review the exact task that will be created.

Request:

- Header or form CSRF token required.
- JSON body:
  - `title` required string.
  - `project` required string.
  - `goal` required string.
  - `mode` optional string.
  - `pipeline` optional string.
  - `target_paths` optional array of strings.
  - `constraints` optional array of strings.

Response:

- `ok` required boolean.
- `preview` required object.

Preview object:

- `normalized_title` required string.
- `project` required string.
- `risk_level` required string.
- `pipeline` required string.
- `target_paths` required array of strings.
- `policy_warnings` required array of strings.
- `brain_snapshot_summary` required object.

### 1.11 `POST /api/tasks/{id}/retry`

Maps to a retry helper around `task_engine.create_task()` using the same packet or selected retry mode.

Purpose: support Failed Task retry actions.

Request:

- Path parameter `id` required string.
- Header or form CSRF token required.
- JSON body:
  - `retry_mode` required string: `same_packet`, `new_run_same_task`, or `manual_inspection_required`.
  - `reason` optional string.

Response:

- `ok` required boolean.
- `task_id` required string.
- `new_run_id` optional string.
- `status` required string.
- `message` required string.

## 2. Screen Inventory

### 2.1 Review Inbox

Primary question: what needs my attention right now?

Components:

- Review task list ordered by risk, age, and blocked status.
- Task row with title, project, risk badge, changed file count, test status, and age.
- Empty state for no pending reviews.
- Project filter.
- Refresh control.
- Link to Queue.

Mobile layout:

- Single-column list.
- Each task uses a compact row with title first, then project, risk, and test status.
- Primary tap target opens the Review Packet.
- Filters collapse behind a simple top control.
- No table layout on mobile.

### 2.2 Review Packet

Primary question: is this diff safe to approve?

Components:

- Task identity header: title, project, task ID, run ID, status, risk level.
- Pipeline summary showing agent1 planner and agent2 implementer.
- Agent1 plan text.
- Brain snapshot summary captured at task creation.
- Changed files summary with per-file risk.
- Diff summary.
- Mobile diff viewer.
- Test results.
- Policy checks.
- Approval controls with risk-specific friction.
- Rollback availability confirmation.
- Reject controls with reason capture.

Mobile layout:

- Header remains compact and readable.
- File summary appears before any hunks.
- Hunks are collapsed by default.
- Approval and rejection controls are sticky at the bottom of the viewport.
- Raw diff is hidden behind a toggle.
- Long plan, test, and policy sections use collapsible panels.

### 2.3 Command Form with Preview

Primary question: what am I about to create?

Components:

- Project selector.
- Goal text area.
- Optional title field.
- Optional target path list.
- Pipeline selector when policy allows.
- Constraint checklist.
- Preview panel populated by `POST /api/tasks/preview`.
- Brain snapshot summary that will be attached to the task.
- Policy warning list.
- Create task button.

Mobile layout:

- Form fields stack vertically.
- Preview appears directly before the final create action.
- Create button remains visually separate from preview generation.
- Long policy warnings wrap naturally and avoid horizontal scrolling.

### 2.4 Queue with Lock Indicators

Primary question: what is running / blocked?

Components:

- Active task list grouped by status.
- Lock indicator per task.
- Active lock list.
- Blocked reason display.
- Worker label.
- Link to task detail or review packet when applicable.
- Stale lock warning state.

Mobile layout:

- Status groups become vertical sections.
- Each task row shows title, status, worker, and lock state.
- Lock details expand inline.
- Active locks use compact cards rather than wide tables.

### 2.5 Project Brain Page

Primary question: what does the system know about this project?

Components:

- Project identity and description.
- Known repo/path details.
- Deployment policy summary.
- Worker availability.
- Project notes.
- Last snapshot timestamp when viewed from a task.
- Link to create a task for this project.

Mobile layout:

- Project identity appears first.
- Operational details are grouped into expandable sections.
- Worker capabilities render as short badges or wrapped text.
- No dense table required.

## 3. Review Packet Schema

The Review Packet is the normalized JSON contract between the execution engine and UI. It must be assembled from artifacts, not inferred from the live worktree alone, so Rusty can trust that the approval view reflects exactly what the agents produced.

Review packet object:

- `task_id` required string.
- `run_id` required string.
- `title` required string.
- `project` required string.
- `status` required string.
- `risk_level` required string: `low`, `medium`, or `high`.
- `pipeline` required object.
- `agent1_plan_text` required string.
- `changed_files` required array of changed file objects.
- `diff_summary` required object.
- `raw_diff` required string.
- `test_results` required array of test result objects.
- `policy_checks` required array of policy check objects.
- `approval_controls` required object.
- `rollback_available` required object.
- `brain_snapshot` required object.
- `artifact_sources` required object.
- `created_at` required ISO-8601 string.
- `updated_at` optional ISO-8601 string.

Pipeline object:

- `name` required string.
- `agent1` required object.
- `agent2` required object.

Pipeline agent object:

- `worker` required string.
- `role` required string.
- `status` required string.
- `started_at` optional ISO-8601 string.
- `completed_at` optional ISO-8601 string.

Changed file object:

- `path` required string.
- `change_type` required string: `added`, `modified`, `deleted`, `renamed`, or `unknown`.
- `risk_score` required integer.
- `risk_level` required string: `low`, `medium`, or `high`.
- `hunk_count` required integer.
- `added_lines` required integer.
- `deleted_lines` required integer.
- `summary` optional string.
- `risk_reason` optional string.

Diff summary object:

- `stats_line` required string.
- `file_count` required integer.
- `added_lines` required integer.
- `deleted_lines` required integer.
- `generated_from` required string, expected `git_diff.patch`.

Test result object:

- `name` required string.
- `command` optional string.
- `status` required string: `passed`, `failed`, `skipped`, `not_run`, or `unknown`.
- `duration_seconds` optional number.
- `summary` optional string.
- `output_artifact` optional string.

Policy check object:

- `id` required string.
- `label` required string.
- `status` required string: `pass`, `fail`, `warning`, or `not_applicable`.
- `message` optional string.
- `blocking` required boolean.

Approval controls object:

- `friction_level` required string: `low`, `medium`, or `high`.
- `confirm_token` required string.
- `confirm_phrase` optional string.
- `requires_scroll_to_bottom` required boolean.
- `requires_all_hunks_expanded` required boolean.
- `requires_typed_confirmation` required boolean.
- `rollback_confirmation_required` required boolean, always `true`.

Rollback availability object:

- `available` required boolean.
- `patch_path` optional string.
- `message` required string.

Brain snapshot object:

- `project` required object.
- `workers` optional array.
- `captured_at` required ISO-8601 string.
- `source` required string, expected `registry/projects.yaml`.

Artifact sources object:

- `worker_packet` required string.
- `agent1_result` optional string.
- `git_diff` optional string.
- `changed_files` optional string.
- `review_summary` optional string.
- `brain_snapshot` required string.

## 4. Approval Friction Model

Approval friction is based on the `risk_level` field from `StandardizedTask.risk_level`. Friction is cognitive and review-oriented. It must require reading, expansion, or confirmation of content, not awkward physical gestures.

### 4.1 Low Risk

- User can approve with a single tap or click.
- Rollback confirmation is still shown before final submission.
- Diff summary and changed file list remain visible near the approval control.
- `rollback_acknowledged` must be submitted as `true`.

### 4.2 Medium Risk

- User must scroll to the bottom of the rendered diff review content before approval is enabled.
- User then confirms approval with one tap or click.
- Rollback confirmation is always shown.
- The UI records `read_receipt.diff_scrolled_to_bottom` as `true`.

### 4.3 High Risk

- User must expand all file hunks before approval is enabled.
- User must type the provided confirm phrase.
- Rollback confirmation is always shown.
- The UI records the expanded file paths and typed confirmation in the approval request.

### 4.4 Shared Rules

- Rejection is always available.
- Failed policy checks that are marked blocking disable approval.
- The approval view must state that approval is not deployment.
- Rollback availability is visible at every risk level, including when rollback is unavailable.

## 5. Mobile Diff Viewer Spec

The mobile diff viewer optimizes for understanding the change before raw patch inspection.

Required behavior:

- Show file summary cards before hunks.
- Each file summary includes filename, added/deleted line counts, hunk count, and risk badge.
- Hunks are collapsed by default.
- Tapping a file expands its hunks.
- Default hunk view omits line numbers.
- Added and deleted lines are visually distinguishable without relying only on color.
- Long lines wrap by default.
- Raw unified diff is available through a `Show raw diff` toggle.
- Raw diff is not the default view.
- Sticky approve and reject controls remain at the bottom of the viewport.
- Sticky controls must not cover the final diff content; the page includes bottom spacing.
- File expansion state contributes to high-risk approval read receipts.

Content order:

1. Task and risk summary.
2. Changed file cards.
3. Expandable hunks.
4. Raw diff toggle.
5. Tests and policy checks.
6. Approval and rejection controls.

## 6. Security Model

Phase UI-0 is a private operational interface, not a public SaaS surface.

Network and process boundaries:

- Flask binds to `127.0.0.1` only.
- Caddy reverse proxies to Flask.
- Caddy restricts access to Tailscale IP range `100.64.0.0/10`.
- Tailscale membership is the authentication boundary for Phase UI-0.
- Phase UI-0 has no separate auth tokens.

Request safety:

- All approval, rejection, creation, preview, and retry actions use `POST`.
- POST actions require a CSRF token bound to the session cookie.
- GET endpoints must not mutate task state.
- API responses must not include secrets, raw environment values, API keys, private SSH keys, or hidden file contents.
- Review packets may include diffs only for the task target paths.

Operational constraints:

- The UI must not auto-deploy.
- Approval must transition task state only according to the scheduler-owned lifecycle.
- SQLite locks remain the only lock mechanism.
- The scheduler owns lock lifecycle.
- The UI displays locks but does not acquire or release them directly.

## 7. ntfy.sh Notification Hooks

ntfy.sh notifications are outbound status hooks. They should be inserted after `record_event()` calls in `task_engine.transition_task()` so notifications follow recorded state changes.

Events that trigger notifications:

- Task reaches `review` status.
- Task transitions to `done`.
- Task transitions to `failed`.
- Task transitions to `canceled`.
- Queue becomes blocked by lock contention.

Review notification:

- Topic: `operator-review`.
- Title: `Operator review required`.
- Message includes task title, project, risk level, and approve URL.
- Priority is based on risk level.
- Click URL opens the Review Packet.

Completion notification:

- Topic: `operator-review`.
- Title indicates `done`, `failed`, or `canceled`.
- Message includes task title, project, and final status.
- Click URL opens task detail or failed task view.

Blocked queue notification:

- Topic: `operator-review`.
- Title: `Operator queue blocked`.
- Message includes blocked task title and lock scope.
- Click URL opens the Queue screen.

Payload fields:

- `topic` required string.
- `title` required string.
- `message` required string.
- `priority` required string or integer.
- `click_url` required string.
- `tags` optional array of strings.

Notification safety:

- Messages must not include secrets.
- Messages should include URLs, not raw artifact paths, unless the URL is Tailscale-restricted.
- Notification failure must not block task state transition.

## 8. Failed Task View

The Failed Task View explains what failed, what remains available for inspection, and which retry paths are safe.

Common components:

- Task identity header.
- Failure type.
- Human-readable failure message.
- Last worker that ran.
- Last known status.
- Preserved worktree path when available.
- Artifact directory when available.
- Relevant log artifact links when available.
- Retry action controls.
- Discard action when policy allows.
- Link back to Queue.

Failure taxonomy:

- `agent1_timeout`
- `agent1_nonzero`
- `codex_timeout`
- `codex_nonzero`
- `codex_no_changes`
- `promotion_failed`
- `preflight_failed`

Failure mappings:

| Failure type | Displayed message | Primary retry action | Secondary action |
| --- | --- | --- | --- |
| `agent1_timeout` | Planner timed out before producing a usable implementation plan. | Re-queue with same packet. | Inspect artifacts. |
| `agent1_nonzero` | Planner exited unsuccessfully. | Re-queue with same packet after reviewing planner output. | Discard task. |
| `codex_timeout` | Implementer timed out before completing the requested changes. | Re-queue as new run for same task. | Inspect preserved worktree. |
| `codex_nonzero` | Implementer exited unsuccessfully. | Inspect worktree before retry. | Re-queue with same packet. |
| `codex_no_changes` | Implementer completed without producing file changes. | Inspect worktree and packet target paths. | Discard task. |
| `promotion_failed` | Task output could not be promoted to the next lifecycle state. | Retry promotion after inspection. | Inspect artifacts. |
| `preflight_failed` | Policy or environment preflight blocked execution before worker work began. | Edit task inputs and create a new task. | Discard task. |

Retry behavior:

- Same-packet retry preserves the original worker packet.
- New-run retry creates a new run ID under the same task ID.
- Manual inspection preserves the worktree and shows the path.
- Retry actions are POST-only and require CSRF protection.
- Retrying never deploys changes.

