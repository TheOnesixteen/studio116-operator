# Standardized Task Object — v1 Final
# Merged from: Gemini (structure), GPT (execution fields), Claude (spec alignment)
# Date: 2026-05-16
# Status: LOCKED — this is the schema both intake entry points must produce

{
  # ── Identity ──────────────────────────────────────────────────────────────
  "id": "uuid-generated-at-creation",
  "title": "string — short human-readable title",
  "goal": "string — full goal statement",
  "requested_by": "rusty",
  "priority": 10,

  # ── Project + Worker ──────────────────────────────────────────────────────
  "project": "string — slug from registry (e.g. kairoke, operator)",
  "task_type": "delegated | health_check | review | planning",
  "agent": "codex | claude_code | gemini_cli | shell_ops",
  "delegation_mode": "string — e.g. live_codex_docs_only, live_codex_model_file_only",

  # ── Scope + Paths ─────────────────────────────────────────────────────────
  # scope = conceptual area ("the findings reader", "the auth layer")
  # target_paths = actual files the agent may touch
  # blocked_paths = explicit no-go list, snapshotted from policies.yaml at compile time
  # origin_directory = where `operator do` was invoked from (for path normalization)
  "scope": ["conceptual area strings"],
  "target_paths": ["explicit file/path list"],
  "blocked_paths": ["snapshotted from policies.yaml at compile time"],
  "origin_directory": "string — realpath of cwd when operator do was invoked",

  # ── Task Content ──────────────────────────────────────────────────────────
  "steps": ["ordered string list"],
  "acceptance_criteria": ["string list"],

  # ── Risk + Normalization ──────────────────────────────────────────────────
  "risk_level": "low | medium | high",
  "normalization_path": "fast | normal | deep",
  "confidence": 0.0,       # 0.0–1.0, set by normalizer, engine uses to gate confirmation

  # ── Policy Enforcement Flags ──────────────────────────────────────────────
  # Defaults are maximally restrictive. Normalizer loosens only when policy allows.
  "write_intent": false,           # GPT: must be explicit — engine pre-flight checks this
  "read_only": true,               # if true, engine blocks any file mutation attempt
  "allow_file_creation": false,    # explicit opt-in for new file creation
  "max_changed_files": 1,          # hard cap — engine rejects diffs that exceed this
  "deployment_allowed": false,     # explicit opt-in for deploy operations

  # ── Approval Gates ────────────────────────────────────────────────────────
  "requires_confirmation": true,   # show Task Object summary and wait for Y/n
  "requires_human_approval": true, # after execution, require approve/reject before merge
  "requires_gemini_review": false, # add Gemini critique pass before execution

  # ── Source Context ────────────────────────────────────────────────────────
  # Preserved for audit trail and engine resumption
  "source_context": {
    "entrypoint": "do | ingest",
    "raw_input": "original string or spec path",
    "spec_path": "path/to/spec.md or null",
    "referenced_artifacts": ["task-id or file path"]
  },

  # ── Routing Transparency ──────────────────────────────────────────────────
  # GPT: show decision summary, not full reasoning
  "routing_reason": "short string — why this agent was chosen",
  "normalization_notes": ["string — what the normalizer inferred and why"]
}
