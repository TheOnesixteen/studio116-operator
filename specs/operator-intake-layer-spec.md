# Studio 116 Operator — Intake Layer Build Spec
**Version:** 1.0  
**Date:** 2026-05-16  
**Status:** Ready for Codex execution  
**Project:** operator  
**Agent:** codex  
**Risk Level:** medium  
**Requires Human Approval:** yes — review diff before merge

---

## Context

Read these files before writing a single line of code:

```
/root/Projects/studio116-operator/OPERATOR.md
/root/Projects/studio116-operator/app/main.py
/root/Projects/studio116-operator/app/task_engine.py
/root/Projects/studio116-operator/app/models.py
/root/Projects/studio116-operator/app/policies.py
/root/Projects/studio116-operator/registry/projects.yaml
/root/Projects/studio116-operator/registry/workers.yaml
/root/Projects/studio116-operator/registry/policies.yaml
```

Understand the existing CLI structure, task lifecycle, and policy enforcement
before writing anything. Do not invent new patterns — extend what is already there.

---

## What You Are Building

The Operator currently requires Rusty to hand-craft every task manually using
`operator task create` with explicit flags. This is the right level of control
but the wrong amount of friction.

You are building an **intake layer** with two new entry points that both compile
down to the existing task creation and execution pipeline:

### Entry Point 1: `operator ingest <spec.md>`
High-ceremony. Parses a structured markdown spec file and creates a task.
Used for complex work where Rusty has already written a detailed spec with Claude.

### Entry Point 2: `operator do "<quick task>"`
Low-ceremony. Takes a plain English string, normalizes it using AI, infers
project context from the current directory, and creates a task.
Used for quick tasks, diagnostics, and ad-hoc requests.

Both entry points produce a **Standardized Task Object** and feed it into the
existing engine. The engine does not care which entry point was used.

---

## The Standardized Task Object

Both entry points must produce this object before the engine sees anything.
This is the contract between intake and execution.

```python
@dataclass(frozen=True)
class StandardizedTask:
    # Identity
    title: str
    goal: str
    requested_by: str = "rusty"
    priority: int = 10

    # Project + Worker
    project: str                    # slug from registry
    task_type: str                  # delegated | health_check | review | planning
    agent: str                      # codex | claude_code | gemini_cli | shell_ops
    delegation_mode: str            # existing delegation mode string

    # Scope + Paths
    scope: list[str]                # conceptual area descriptions
    target_paths: list[str]         # explicit files the agent may touch
    blocked_paths: list[str]        # snapshotted from policies.yaml at compile time
    origin_directory: str           # realpath of cwd when `operator do` was invoked

    # Task Content
    steps: list[str]
    acceptance_criteria: list[str]

    # Risk + Normalization
    risk_level: str                 # low | medium | high
    normalization_path: str         # fast | normal | deep
    confidence: float = 0.0        # 0.0–1.0

    # Policy Enforcement — defaults are maximally restrictive
    write_intent: bool = False
    read_only: bool = True
    allow_file_creation: bool = False
    max_changed_files: int = 1
    deployment_allowed: bool = False

    # Approval Gates — defaults require human in the loop
    requires_confirmation: bool = True
    requires_human_approval: bool = True
    requires_gemini_review: bool = False

    # Source Context — preserved for audit trail
    source_context: dict = field(default_factory=dict)
    # {
    #   "entrypoint": "do | ingest",
    #   "raw_input": "original string or spec path",
    #   "spec_path": "path or null",
    #   "referenced_artifacts": []
    # }

    # Routing Transparency
    routing_reason: str = ""
    normalization_notes: list[str] = field(default_factory=list)
```

Add this dataclass to `app/models.py`.

---

## File Structure

Create these new files. Do not modify existing files except where explicitly
instructed below.

```
app/
  intake/
    __init__.py
    normalizer.py       # Three-level normalization logic + AI routing
    spec_parser.py      # Markdown spec parser → StandardizedTask
    adhoc_parser.py     # `operator do` string → StandardizedTask
    risk_scorer.py      # Scores risk level and normalization path
    context_resolver.py # Infers project from cwd, resolves paths
```

---

## Spec: `app/intake/context_resolver.py`

Resolves project context from the current working directory.

```python
def resolve_project_from_cwd(cwd: str, registry: dict) -> str | None:
    """
    Given a current working directory and the loaded projects registry,
    return the project slug whose repo_path is a prefix of cwd.
    Returns None if no match found.
    """
```

```python
def snapshot_blocked_paths(project_slug: str, policies: dict) -> list[str]:
    """
    Pull forbidden_paths and blocked_paths from policies.yaml for this project
    at compile time. These are baked into the StandardizedTask so the engine
    has an unalterable blacklist.
    """
```

```python
def normalize_target_paths(paths: list[str], origin_dir: str) -> list[str]:
    """
    Resolve all relative paths against origin_dir using os.path.realpath.
    Reject any path that resolves outside the project repo_path.
    """
```

---

## Spec: `app/intake/risk_scorer.py`

Scores incoming requests before normalization begins.

```python
# HIGH RISK triggers — these words in the goal string force deep normalization
HIGH_RISK_KEYWORDS = [
    "deploy", "production", "delete", "rm", "drop", "migrate",
    "database", "secret", "auth", "password", "token", "key",
    "payment", "billing", "ssl", "caddy", "nginx", "firewall",
    "docker", "compose", "systemctl", "cron", "sudo"
]

# ARCHITECTURE triggers — route to Claude instead of Codex
ARCHITECTURE_KEYWORDS = [
    "architecture", "design", "structure", "refactor", "rewrite",
    "strategy", "approach", "how should", "what's the best",
    "multi-project", "cross-project", "review", "critique", "audit"
]

# GEMINI REVIEW triggers — add Gemini pass before execution  
GEMINI_REVIEW_TRIGGERS = [
    "security", "auth", "secrets", "deploy", "production",
    "policy", "permissions", "delete", "drop", "irreversible"
]
```

```python
def score_risk(goal: str, project: str, registry: dict) -> dict:
    """
    Returns:
    {
        "risk_level": "low | medium | high",
        "normalization_path": "fast | normal | deep",
        "requires_gemini_review": bool,
        "escalate_to_claude": bool,
        "triggered_keywords": [str]
    }
    """
```

---

## Spec: `app/intake/normalizer.py`

Three-level normalization. Codex is the default normalizer. Claude escalates
on ambiguity or architecture. Gemini reviews on risk.

### Level 1 — Fast (under 3 seconds)
For clear, low-risk tasks with confident project inference.
- No AI call
- Deterministic parsing only
- No confirmation required if confidence >= 0.85

### Level 2 — Normal (5–15 seconds)  
For ambiguous tasks where project is clear but intent needs interpretation.
- Codex normalizes
- Show interpreted task to Rusty
- Require Y/n confirmation before queuing

### Level 3 — Deep (15–45 seconds)
For dangerous or broad tasks.
- Claude normalizes (not Codex — these need architectural judgment)
- Gemini critique pass if `requires_gemini_review` is true
- Require explicit confirmation
- `max_changed_files` defaults to 1 unless spec explicitly states otherwise

### AI Routing Logic

```python
def select_normalizer(risk_score: dict) -> str:
    """
    Returns "local" | "codex" | "claude"
    
    local:  confidence >= 0.85, risk=low, no ambiguous keywords
    codex:  default for implementation tasks, risk=low|medium
    claude: architecture keywords detected, or risk=high, or
            no project can be confidently inferred, or
            goal is fuzzy ("fix the broken thing", "make it better")
    """
```

### Codex Normalization Prompt Template

When calling Codex to normalize a quick task, use this prompt structure:

```
You are normalizing a quick task for the Studio 116 Operator.

Project: {project_slug}
Project stack: {stack from registry}
Current directory: {origin_directory}
Raw input: "{raw_goal}"

Produce a JSON object with these fields:
- title: short task title (max 60 chars)
- goal: clear goal statement (1-2 sentences)  
- steps: ordered list of concrete steps (max 5)
- target_paths: list of files likely involved (be specific, not "*")
- acceptance_criteria: list of testable outcomes
- task_type: delegated | health_check | review | planning
- delegation_mode: which existing delegation mode fits best
- write_intent: true if files will be changed, false if read-only
- confidence: 0.0–1.0 how confident you are in this interpretation

If target_paths is ambiguous, return an empty list — do not guess file paths.
If confidence is below 0.7, explain why in a normalization_note.

Return only valid JSON. No explanation.
```

### Display Format

After normalization, show this to Rusty — no long explanations:

```
Interpreted task:
  Project:  kairoke
  Goal:     Add error handling to the Mureka API integration
  Worker:   Codex
  Files:    app/mureka.py, tests/test_mureka.py
  Risk:     low
  Why:      Implementation task in known project, clear target files

No files will be changed until you approve.
Proceed? [Y/n]
```

---

## Spec: `app/intake/spec_parser.py`

Parses a structured markdown spec file into a StandardizedTask.

### Expected Spec Format

The parser must handle specs written in this format (the RedLetters format):

```markdown
# Task Title

## Goal
One to three sentence description of what should be accomplished.

## Project
project-slug

## Agent
codex | claude_code | gemini_cli | shell_ops

## Delegation Mode
live_codex_docs_only | live_codex_model_file_only | etc.

## Target Files
- path/to/file1.py
- path/to/file2.py

## Steps
1. First step
2. Second step
3. Third step

## Acceptance Criteria
- Criterion one
- Criterion two

## Risk Level
low | medium | high

## Notes
Optional free text. Preserved in source_context.
```

All sections except `# Title`, `## Goal`, and `## Project` are optional.
Missing sections get safe defaults (read_only=true, requires_confirmation=true,
max_changed_files=1).

```python
def parse_spec(spec_path: str) -> StandardizedTask:
    """
    Reads a markdown spec file.
    Validates required sections are present.
    Snapshots blocked_paths from policies.yaml.
    Returns StandardizedTask with source_context.entrypoint = "ingest".
    Raises SpecParseError with clear message if required sections are missing.
    """
```

---

## Spec: `app/intake/adhoc_parser.py`

Handles `operator do "<quick task>"` entry point.

```python
def parse_adhoc(raw_input: str, cwd: str) -> StandardizedTask:
    """
    1. Resolve project from cwd using context_resolver
    2. Score risk using risk_scorer
    3. Select normalization level
    4. Call appropriate normalizer (local/codex/claude)
    5. Display result to user
    6. Wait for confirmation if required
    7. Return StandardizedTask with source_context.entrypoint = "do"
    """
```

### Wide Scope Protection

If `operator do` is invoked with a scope that resolves to a top-level directory
or contains `*`, force Level 2 (normal) normalization minimum and require
explicit confirmation even if confidence is high.

---

## CLI Integration

Add these two commands to `app/main.py`:

```python
# operator ingest <spec_path>
# Parses spec file, shows interpreted task, asks for confirmation, queues task
parser_ingest = subparsers.add_parser("ingest", help="Ingest a spec file and create a task")
parser_ingest.add_argument("spec_path", help="Path to markdown spec file")
parser_ingest.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

# operator do "<goal>"
# Normalizes quick task, shows interpretation, asks for confirmation, queues task  
parser_do = subparsers.add_parser("do", help="Quickly queue a task from plain English")
parser_do.add_argument("goal", help="Plain English task description")
parser_do.add_argument("--project", "-p", help="Override project inference")
parser_do.add_argument("--agent", "-a", help="Override agent selection")
parser_do.add_argument("--dry-run", action="store_true", help="Show interpreted task without queuing")
parser_do.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
```

Both commands must call `task_engine.create_task_from_standardized()` — a new
function that accepts a StandardizedTask and creates the DB record.

---

## Engine Integration

Add one new function to `app/task_engine.py`:

```python
def create_task_from_standardized(task: StandardizedTask) -> str:
    """
    Accepts a StandardizedTask object.
    Validates it against policies.yaml:
      - agent must be in registry
      - project must be in registry  
      - write_intent=True requires agent in allowed_write_agents
      - target_paths must not overlap with blocked_paths
      - max_changed_files enforcement noted in task metadata
    Creates DB record.
    Returns task ID.
    """
```

This function is the bridge between the intake layer and the existing engine.
It must enforce policy — the intake layer should not trust itself.

---

## Safety Rules for This Build

- Do NOT modify the scheduler
- Do NOT modify the lock system
- Do NOT modify existing task_engine functions — add only
- Do NOT modify the database schema
- Do NOT add new dependencies without checking what's already installed
- Do NOT hardcode API keys — use the existing config/env pattern
- The Anthropic API key is at `~/.anthropic_key` — load it the same way the
  rest of the codebase does
- If Codex normalization requires an API call, use the existing Codex CLI
  adapter pattern, do not call OpenAI API directly

---

## Acceptance Criteria

- [ ] `operator ingest /path/to/spec.md` parses a spec and creates a task
- [ ] `operator ingest` fails with a clear error if required sections are missing
- [ ] `operator do "add tests for the findings reader"` from inside
      `/root/Projects/redletters` correctly infers project=redletters
- [ ] `operator do "deploy to production"` triggers deep normalization and
      requires_gemini_review=true
- [ ] `operator do "fix the thing"` with no project inferable asks for
      --project flag rather than guessing
- [ ] Both commands show the interpreted task before queuing
- [ ] Both commands respect --yes flag to skip confirmation
- [ ] Both commands respect --dry-run flag to show without queuing
- [ ] StandardizedTask blocked_paths is populated from policies.yaml at
      compile time, not at execution time
- [ ] `create_task_from_standardized` rejects a task where write_intent=True
      but agent is read-only
- [ ] `node --check` equivalent (python -m py_compile) passes on all new files
- [ ] All new functions have docstrings
- [ ] No secrets appear in any output or artifact

---

## What This Does NOT Build

- No webhook intake (Phase 4)
- No browser/mobile interface (Phase 4)
- No autonomous goal decomposition without human confirmation
- No changes to the existing delegation pipeline
- No new database tables
- No Gemini CLI integration (the review flag is set but Gemini CLI call
  is a stub that prints "Gemini review: [not yet implemented]" — wire it up
  in a follow-on task)

---

## Handoff Note to Codex

After completing this build:
1. Run `python -m py_compile` on every new file
2. Run `scripts/operator ingest` with a test spec and show the output
3. Run `scripts/operator do "check kairoke health"` from inside
   `/root/Projects/kairoke.com` and show the output
4. Run `scripts/operator do "deploy to production"` and confirm it
   triggers deep normalization
5. Show the git diff --stat
6. Do NOT run the scheduler
7. Do NOT push to GitHub — Rusty reviews the diff first
