# Studio 116 Operator — Founding Charter
**Version:** 1.2  
**Author:** Rusty (Studio 116)  
**Date:** April 13, 2026  
**Status:** Active — Master Source of Truth  
**Applies To:** All human and AI contributors working on the Studio 116 Operator project

---

## 1. Mission

Build a persistent orchestration agent — the **Studio 116 Operator** — that lives on the DigitalOcean droplet at `do.116.studio` and serves as Rusty’s single intelligent operational partner.

The Operator must be able to:

- Accept goals in plain English from Rusty
- Understand which project, system, or site is involved
- Break large goals into smaller, manageable tasks
- Decide which worker or tool is best suited for each task
- Delegate work to Claude Code, GPT Codex, Shell/Ops tools, and future workers
- Track progress, store outputs, and summarize results clearly
- Know when to stop, escalate, or ask for approval
- Operate safely around live infrastructure, credentials, and production systems

The Operator is not a novelty.  
It is not a toy chatbot.  
It is intended to become the operational brain behind Studio 116.

---

## 2. Core Philosophy

The Operator exists to make Rusty more effective without requiring Rusty to become a full-time developer or systems engineer.

It must behave like a reliable chief of staff:

- calm
- honest
- methodical
- practical
- safety-aware
- capable of initiative within bounds

### Guiding principles

1. **Reliability over speed**  
   A slower correct action is better than a fast wrong action.

2. **Clarity over cleverness**  
   The system should be understandable, inspectable, and recoverable.

3. **Bounded autonomy**  
   The Operator may act independently within defined limits, but must not take irreversible or risky production actions without approval.

4. **Escalate early, not late**  
   If the path becomes uncertain, expensive, or fragile, the Operator should stop and report rather than bluff or thrash.

5. **Use the right worker for the job**  
   Claude, Codex, Gemini, Grok, and future tools are workers. The Operator is the brain.

6. **Protect live systems**  
   Production stability, credentials, and recoverability are more important than automation ambition.

---

## 3. The Human

**Rusty** is the sole human operator of Studio 116.

Rusty works primarily from a Mac and launches agents via terminal. Rusty is highly capable, creative, and technical, but does not want to hand-build every system component personally. Rusty wants to describe outcomes in plain English and have the system determine safe and intelligent next steps.

### Rusty’s preferences

- plain English task intake
- clear summaries
- honest status reporting
- minimal fluff
- practical progress
- visible artifacts
- low tolerance for rabbit holes
- strong preference for official APIs over brittle hacks
- no silent destructive actions

The Operator should optimize for Rusty’s working style.

---

## 4. What the Operator Is

The Operator is a **persistent Python orchestration service** running on the droplet.

It includes:

- a task queue
- a project registry
- worker adapters
- a scheduler
- a safety policy engine
- task lifecycle tracking
- CLI interaction
- artifact and log storage
- locking and concurrency control
- optional webhook intake
- future dashboard support

The Operator is the single control point between Rusty and the underlying worker ecosystem.

---

## 5. What the Operator Is Not

The Operator is **not**:

- a generic chatbot
- tied to one model provider
- a replacement for n8n
- a fully autonomous deployer
- a CI/CD platform
- a multi-user SaaS application
- an excuse to hide uncertainty or pretend success

n8n remains an automation and integration layer.  
The Operator remains the orchestration and decision layer.

---

## 6. Infrastructure Baseline

The following infrastructure already exists and must be treated as real, authoritative context — not rebuilt from scratch.

### Core infrastructure

| Resource | Details |
|---|---|
| Droplet | `do.116.studio` / `159.65.187.30`, Ubuntu 24.04, 2GB RAM / 2vCPU |
| SSH alias | `ssh digitalocean` |
| Claude Code launch | `116studio-ai` |
| GitHub | `TheOnesixteen/116.studio-AI` |
| Sync scripts | `sync-up`, `sync-down` |
| SiteGround | SSH/SFTP on port `18765` |
| SiteGround key | `~/.ssh/siteground_key` |

### Services currently running on droplet

| Service | Details |
|---|---|
| n8n | Docker container `n8n-n8n-1`, port 5678 |
| kairoke Flask app | systemd `kairoke.service`, port 5000 |
| Caddy | Reverse proxy and SSL |
| suno-api | Docker `n8n-suno-api-1`, port 3000 — deprecated |

### Credentials and key locations

| Key | Location |
|---|---|
| Anthropic API | `~/.anthropic_key` |
| n8n API | `~/.n8n_api_key` |
| SiteGround SSH | `~/.ssh/siteground_key` |
| Suno/2captcha | `/root/n8n/suno.env` — deprecated |

These locations are not to be copied into repos or exposed in logs.

---

## 7. Projects Under Management

### Client sites
- `kensingtonpool.com`
- `skilagrange.com`
- `kdomusic.com`
- `combsplumbing.com`
- `robinolinger.com`

### Personal sites
- `116.studio`
- `rustyo.com`
- `kairoke.com`
- `thetrouper.com`

### Deploy scripts
- `deploy-kensington`
- `deploy-ski`
- `deploy-katie`
- `deploy-combs`
- `deploy-robin`
- `deploy-studio`
- `deploy-rustyo`
- `deploy-kairoke`
- `deploy-trouper`

These are part of the live operating environment and should be treated as first-class tools and targets.

---

## 8. Active Strategic Projects

### 8.1 kairoke.com
High-priority AI karaoke platform.

Flow:
Guest scans QR code → chats with KAI → submits song request → n8n workflow runs → song is generated → resulting URL is returned to kairoke.com.

#### Current decision
`suno-api` is deprecated after repeated browser automation failure and wasted time/cost.

#### Replacement direction
Use **Mureka API** as the song generator:
- API-first
- bearer token authentication
- predictable REST workflow
- no browser automation
- better fit for a durable product

#### Immediate dependency
Mureka API key acquisition is required before integration work can proceed.

### 8.2 studio116-operator
The system described in this document.

### 8.3 skilagrange.com
Lead form flow into n8n and Twilio SMS. Operational and useful as an early proving ground for tasking, inspection, and workflow review.

---

## 9. Repository and File Structure

### Canonical repo location

```text
/root/Projects/studio116-operator/

TheOnesixteen/studio116-operator

studio116-operator/
  app/
    main.py
    config.py
    db.py
    models.py
    router.py
    scheduler.py
    policies.py
    state_manager.py
    task_engine.py
    artifact_store.py
    locks.py
    events.py
  adapters/
    base.py
    claude_code.py
    codex.py
    shell.py
    gemini.py
    grok.py
  workers/
    planner.py
    implementer.py
    verifier.py
    deployer.py
  tools/
    git_tools.py
    docker_tools.py
    caddy_tools.py
    systemd_tools.py
    n8n_tools.py
    deploy_tools.py
    siteground_tools.py
    log_tools.py
    secret_tools.py
    repo_tools.py
  registry/
    projects.yaml
    workers.yaml
    tools.yaml
    policies.yaml
  runtime/
    tasks/
    logs/
    artifacts/
    worktrees/
    sessions/
  prompts/
    planner.md
    coder.md
    verifier.md
    deployer.md
  scripts/
    operator-start
    operator-stop
    operator-status
    task-submit
  tests/
  OPERATOR.md
  README.md
```

### Current Proven State

Phase 2 has proven four narrow writable Codex lanes for the Operator repo:

- `live_codex_docs_only` for policy-whitelisted docs targets in `registry/policies.yaml`.
- `live_codex_tests_only` for `tests/test_*.py` only, with content hardening.
- `live_codex_policy_file_only` for `app/policies.py` only. Phase 2.5a is smoke-proven.
- `live_codex_model_file_only` for `app/models.py` only. Phase 2.6a is smoke-proven.

No other app files, registry files, tests, infrastructure, runtime files, deploy scripts, service files, or config files are writable Codex targets unless a future phase explicitly proves and documents a new lane.

### Phase Milestones

Current milestone tags:

- `phase2.4a-tests-whitelist-stable`
- `phase2.4b-tests-content-hardened`
- `phase2.4b-stale-patch-recovery`
- `phase2.5a-policy-file-lane-stable`
- `phase2.5a-policy-file-smoke-proven`
- `phase2.6a-model-file-lane-stable`
- `phase2.6a-model-file-smoke-proven`

Phase 2.7a currently includes commit `1ad78d5`, which adds a characterization test for recurring Codex stderr noise.

### Current Safety Model

Live Codex writes remain bounded by:

- registry-backed whitelists as the source of truth
- isolated delegated worktrees
- one writable Codex task at a time
- scheduler-owned SQLite locks
- preflight before worker launch
- post-run changed-file and content validation
- mandatory stop in `review`
- canonical checkout untouched until explicit approval
- approval applying a patch only after validation
- rejection discarding delegated worktree changes only
- no auto-commit, auto-merge, auto-push, deploy, package install, or network-dependent work

### Phase 2.7 Direction

Phase 2.7a is a hardening and cleanup phase, not a writable-scope expansion phase.

The characterization test in `tests/test_phase27a_codex_stderr_noise.py` proves that the recurring Codex stderr message `failed to record rollout items` is captured as raw stderr in Operator records, including `worker_executions.stderr` and `worker_result.json`, but is non-blocking when Codex exits successfully and is not promoted into human-facing review summaries.

Next cleanup work should reduce silent complexity and naming drift without changing delegation mode strings, smoke-proven artifact filenames, check names used in existing artifacts, or approve/reject behavior.
# Studio 116 Operator — Changelog
*Append this section to OPERATOR.md under a new `## Changelog` heading.*

---

## Changelog

### 2026-05-16 — Trading System Build-Out

**What was done:**

Complete build and tuning of the Studio 116 ghost trading system. This work happened in parallel with operator development. The trading system is a separate project from the Operator but shares the same droplet and represents the first real use case the Operator will eventually orchestrate.

**Codex sessions completed:**

1. **Read-only audit** — Full inventory of dashboard paths, data sources, stale files, and stock data path bugs. Identified that Wave Rider Stocks was reading the wrong log file (runs-v2 instead of wave-rider-stocks-v2).

2. **Dashboard data path fixes** — Fixed stock builder to read correct log. Added `candidates.json` generation to Sniper. Updated all dashboard pages to derive metrics from live ledger data instead of hardcoded stale values.

3. **Dashboard page split and rebuild** — Replaced 4 pages with 6 distinct pages, each with a dedicated color theme. Created new `build-analysis-json.js` script implementing the "did vs should have done" analysis loop. Added script to cron build.

4. **Strategy gates deployed:**
   - Hard EMA cross staleness gate on Wave Rider Crypto: `bars_since_ema_cross > 10` → skip with reason `ema_cross_too_stale`. Evidence: early-entry PF 0.95 vs late-entry PF 0.60 across 89 historical trades.
   - Sentiment gate removed from Wave Rider Stocks: `sentimentOk` always returns true. Was blocking all entries.

5. **Trailing stop widened:** `TRAILING_STOP_PCT` changed from 1.2% to 2.0% on Wave Rider Crypto. Evidence: 66% of 89 closed trades were trailing stop exits. Winners were being cut before reaching the 1.8% take profit target.

**Key architectural decisions made:**

| Decision | Rationale |
|---|---|
| "Did vs should have done" loop as core tuning signal | Gap between what the system did and what it should have done is the tuning target. Closing that gap = making money. |
| One recommended tuning action at a time | Avoid parameter churn. Rusty approves all changes before they go live. |
| Ghost mode until PF > 1.15 sustained | Don't risk real capital on a losing system. |
| Dashboard pages answer three questions | What is happening? Is it good or bad? What should I watch next? |

**Files created or significantly changed:**

```
/root/Projects/trader.116.studio/scripts/build-analysis-json.js   (NEW)
/root/Projects/trader.116.studio/scripts/build-all-trader-dashboards.sh  (updated — 4 builders now)
/root/Projects/trader.116.studio/scripts/build-ghost-ledger-json.js  (updated — telemetry recovery)
/root/Projects/trader.116.studio/scripts/build-wave-rider-dashboard-json.js  (updated — correct stock log)
/root/n8n/trading-bot/generate-wave-rider-crypto-workflow.js  (updated — EMA gate + trailing stop)
/root/n8n/trading-bot/generate-workflow.js  (updated — sentiment bypass)
/var/www/trader/index.html  (Command Center — full rebuild)
/var/www/trader/sniper/crypto/index.html  (NEW)
/var/www/trader/sniper/stocks/index.html  (NEW)
/var/www/trader/waverider/crypto/index.html  (full rebuild)
/var/www/trader/waverider/stocks/index.html  (full rebuild)
/var/www/trader/performance/index.html  (full rebuild — Tuning Lab)
```

**Current system state:** See `/root/Projects/trader.116.studio/docs/TRADING-SYSTEM.md`

---

### Lessons Learned from Trading System Build (Relevant to Operator Design)

These emerged from the Codex sessions and are relevant to how the Operator should handle similar work:

1. **Always read the data shape before writing builders.** Codex spent time patching code that was reading the wrong fields because the actual log schema wasn't inspected first. The Operator should require agents to read source data before writing builders.

2. **Wrong log file = silent empty dashboard.** The stocks builder was reading `runs-v2.jsonl` instead of `wave-rider-stocks-v2.jsonl`. Everything compiled and ran, but the output was silently empty. The Operator should verify that generated outputs contain expected data, not just that they exist.

3. **n8n API strips active status on PUT — strip read-only fields before push.** Required several iterations to discover which fields are read-only. Now documented in TRADING-SYSTEM.md.

4. **Sentiment gates need real data before they're useful.** Bypassing the sentiment gate entirely was the right call for stocks with zero trades. A gate that blocks 100% of entries is not a gate — it's a wall. Gates should be evaluated against real outcomes before being trusted.

5. **Git repo initialization was deferred.** `/root/Projects/trader.116.studio/.git` exists as an empty directory. The project has no version control. This is a risk — if a build script is broken by a Codex change, there is no rollback. The Operator should initialize this repo before the next agent session touches it.
