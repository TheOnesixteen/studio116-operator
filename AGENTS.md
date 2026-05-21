# AGENTS.md

This repo builds the Studio 116 Operator.

Read `OPERATOR.md` first. It is the master source of truth.

Rules:
- Never auto-deploy
- Never expose secrets
- Use SQLite locks only
- Scheduler owns lock lifecycle
- Build Phase 1 only unless explicitly told otherwise
- Keep implementation simple, inspectable, and resumable

Phase 2.3 whitelist is fully smoke-proven.

Worker Ecosystem:
- `claude_code`: pipeline coordinator and planner — authors the implementation plan consumed by downstream workers (e.g. codex) in sequential runs — and handles architecture decisions, ambiguous debugging, repo comprehension, code review, prompt design, and multi-step reasoning.
- `codex`: implementer for scoped file changes, test execution, refactoring, terminal execution, and test-fix cycles.
- `gemini_cli`: reviewer and second opinion for broad critique, alternative reasoning, spec-gap detection, risk identification, and validation before trust expands to writes.
- `shell_ops`: native ops and diagnostics worker for log inspection, service status, Docker checks, network validation, and disk or memory checks.
