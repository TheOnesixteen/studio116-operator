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
