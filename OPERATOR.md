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
