# Studio 116 — Daily Startup Runbook

Use this when you reboot your Mac or start a fresh work session.

## Purpose
This note is only for **starting fresh**.

It tells you:
- what to check
- what to run
- how to start Claude
- how to start Codex

It does **not** track project status or milestones.  
Project state belongs in:
- `OPERATOR.md`
- commit history
- tags
- recap notes

---

# Important: where commands are run

Commands that start with:

```bash
ssh do-tailscale ...
```

are meant to be run from your **Mac terminal**, not from a shell that is already open on the droplet.

Once you are already on the droplet and see a prompt like:

```text
root@do:~#
```

do **not** run `ssh do-tailscale ...` again from there.

---

# 1) First: make sure Tailscale is connected

## Check
- Look for the Tailscale icon in the Mac menu bar
- Make sure it is green / connected

## If needed
```bash
open -a Tailscale
```

If Tailscale is disconnected, connect it before doing anything else.

---

# 2) Verify the droplet is healthy

Run this from your **Mac**:

```bash
ssh do-tailscale "docker ps && systemctl is-active kairoke"
```

## Expected
- Docker containers are running
- `kairoke` says `active`

## If something is down
Run this from your **Mac**:

```bash
ssh do-tailscale "cd /root/n8n && docker compose up -d"
ssh do-tailscale "systemctl start kairoke"
```

---

# 3) Start Claude Code

Run this from your **Mac**:

```bash
116studio-ai
```

At the start of every Claude session, give this instruction:

```text
Read /root/Projects/studio116-operator/OPERATOR.md first.
Current phase: 2.7a — hardening/cleanup only, no scope expansion.
```

## Note
`116studio-ai` currently uses the `digitalocean` alias (public IP).  
That still works fine — Tailscale is not required for it.

---

# 4) Start Codex

Run this from your **Mac**:

```bash
ssh do-tailscale
```

Then, once connected to the droplet, run:

```bash
cd /root/Projects/studio116-operator
codex
```

At the start of every Codex session, give this instruction:

```text
Read OPERATOR.md first. Current phase: 2.7a.
Do not broaden writable scope. Do not jump to Phase 3.
```

---

# 5) Operator repo location

On the droplet:

```bash
/root/Projects/studio116-operator
```

---

# 6) Quick health check (run anytime)

Run this from your **Mac**:

```bash
ssh do-tailscale "
echo '=== Docker ===' && docker ps --format 'table {{.Names}}\t{{.Status}}'
echo '=== Kairoke ===' && systemctl is-active kairoke
echo '=== Disk ===' && df -h / | tail -1
echo '=== RAM ===' && free -h | grep Mem
"
```

---

# 7) Daily SSH aliases

Use these from your **Mac**:

```bash
ssh do-tailscale
ssh digitalocean
ssh siteground
```

## Preferred for daily Operator work
```bash
ssh do-tailscale
```

---

# 8) Key paths

## Operator repo
```bash
/root/Projects/studio116-operator
```

## Mac automation scripts
```bash
/root/Projects/macbook-is-ai
```

## Kairoke app
```bash
/root/Projects/kairoke.com
```

## n8n compose
```bash
/root/n8n/docker-compose.yml
```

---

# 9) Site deployments

Site deployment commands are **not part of the daily Operator startup flow**.

Do not rely on them here unless they have been separately validated in the exact shell context you plan to use.

If needed later, keep site deployment instructions in a separate deployment note.

---

# 10) Super short version

If you just want the fast path, run this from your **Mac**:

```bash
open -a Tailscale
ssh do-tailscale "docker ps && systemctl is-active kairoke"
116studio-ai
ssh do-tailscale
```

Then, on the droplet:

```bash
cd /root/Projects/studio116-operator
codex
```

---

# 11) Reminder

This file is for **startup steps only**.

Do not use it to track:
- current phase details
- commit history
- tags
- lane milestones
- implementation notes

That belongs elsewhere.

## Latest checkpoint - RedLetters scaffold promoted

- Operator milestone tag: phase2.10g-redletters-scaffold-promoted
- RedLetters repo commit: 27e5f65 Add initial RedLetters Operator scaffold
- Proven: external docs lane, external scaffold lane, Codex execution, review gate, promotion into real external repo.
- RedLetters currently has: app factory, config, routes, base template, stylesheet, schema, requirements, and architecture docs.
- Next recommended phase: RedLetters Mission 003 - run/install/test scaffold locally, then add minimal app startup/test command.
- Do not broaden deployment permissions yet.
- Keep RedLetters deployment disabled until local app smoke test passes.

## Latest checkpoint - RedLetters scaffold smoke test passed

- RedLetters commit: 3290cb2 Add pytest test runner
- RedLetters scaffold installs in venv successfully.
- Smoke test passes with pytest: 1 passed.
- Proven: Operator-built scaffold can be installed and tested locally.
- Next recommended phase: RedLetters Mission 004 - add minimal app run entrypoint or first DB initialization utility, still no deployment.

## Latest checkpoint - RedLetters routes smoke test passed

- RedLetters commit: b139a6a Register routes in app factory
- Local Flask app boots on 127.0.0.1:5016.
- Verified routes:
  - / returns RedLetters MVP route scaffold JSON.
  - /health returns {"status":"ok"}.
  - /healthz returns {"status":"ok"}.
- Next recommended phase: RedLetters Mission 005 - database initialization utility.
