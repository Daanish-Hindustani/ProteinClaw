# NOTES.md — Cross-session engineering notebook

**Purpose:** A persistent, append-only log of fixes, gotchas, decisions, and important context that future Claude Code sessions (or human teammates) need to understand prior work. This is **the** place to leave breadcrumbs for the next session.

**Audience:** future-you, future Claude, future teammate. Assume they have **zero** memory of the current session.

---

## When to write here

Write a new entry when any of these happen:

- **A non-obvious fix** that the next person would otherwise re-debug from scratch.
- **A gotcha or footgun** you hit (and ideally how to spot it earlier next time).
- **A decision** that isn't captured in the PRD, ARCHITECTURE, or PLAN — and that someone could reasonably reverse without realising why it was made.
- **A workaround** for a tool / dep / API quirk (with the upstream issue link if any).
- **A partial implementation** — what's stubbed, what's untested, what's known-broken. Be honest (CLAUDE.md "Honesty about implementation state").
- **A pinned version** that matters (e.g. "dgl must be 2.0.0 for the RFD3 image; 2.1+ breaks SE3Transformer build").
- **A failed approach** that looked reasonable but didn't work. Saves the next person an hour.

**Do not** write here for:

- Things already in the PRD, ARCHITECTURE, PLAN, or CLAUDE — link to them instead.
- Routine status updates ("finished Task 2"). The git log is for that.
- Active debugging in progress — that goes in `DEBUG.md` (per CLAUDE.md "Debug workflow") and only moves here once resolved.

---

## Entry format

Append entries to the bottom of the relevant section. **Never rewrite or delete past entries** — strike through with `~~text~~` and add a follow-up entry if something is later found to be wrong.

```markdown
### YYYY-MM-DD — <short title>
**Context:** what was being worked on / what triggered this note
**Finding / Decision / Fix:** the thing the next person needs to know
**Why it matters:** what breaks or wastes time if this is forgotten
**Links:** commit SHA, PR #, file:line, DEBUG.md entry, upstream issue
```

Keep entries tight — one screen max per entry. If something needs a long writeup, link out to a dedicated doc.

---

## Sections

Group by area so the file stays navigable as it grows. Add a new section when the existing ones don't fit.

### Tooling & environment

(Docker, CUDA, drivers, conda/uv, weight caches, host setup.)

#### 2026-05-23 — Lambda VM came as bare Ubuntu 24.04, NOT Lambda Stack
**Context:** First Phase 1 session. SETUP.md §1 says "Lambda's base image ships with NVIDIA drivers, CUDA, Docker, and the NVIDIA Container Toolkit pre-installed." That was not true for this instance — `nvidia-smi` and `docker` were both missing from a fresh A100 SXM4 40GB VM (image: Ubuntu 24.04.2 LTS).
**Fix that worked (run in this order, all noninteractive):**
1. `sudo apt-get update && sudo apt-get install -y ubuntu-drivers-common`
2. `sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y nvidia-driver-580-server nvidia-utils-580-server` (avoids the debconf "pending kernel upgrade" whiptail that breaks under non-tty)
3. `sudo modprobe nvidia nvidia_uvm nvidia_drm` — no reboot needed; DKMS had already built the module against the running kernel (6.8.0-62)
4. `sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io` + `sudo usermod -aG docker ubuntu`
5. NVIDIA Container Toolkit via the upstream apt repo (gpgkey from nvidia.github.io/libnvidia-container/gpgkey), then `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`
6. Verify: `sudo docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`
**Why it matters:** Phase 1 (and every later phase) assumes the GPU+Docker stack is present. If SETUP.md sends a future contributor down the "everything's pre-installed" path, they'll waste time. Update SETUP.md to flag that the base image varies and link this entry.
**Driver pick:** `nvidia-driver-580-server` (stable, supports CUDA 12.x). 595 is newer but more bleeding-edge; 535 is older but distro-default. Going with 580 was deliberate.
**Links:** Phase 1 commit (TBD); SETUP.md §1 should be updated.

#### 2026-05-23 — Docker group membership doesn't propagate into the current shell
**Context:** After `usermod -aG docker ubuntu`, `docker ps` from the existing shell still fails with `permission denied while trying to connect to the docker API`.
**Fix:** Either re-login (drop SSH + reconnect) or wrap one-off commands in `sg docker -c '...'`. `sg` uses `/bin/sh` so `source venv/bin/activate` fails — wrap further: `sg docker -c 'bash -c "source .venv/bin/activate && ..."'`.
**Why it matters:** Phase 1 GPU smoke test (`pytest -m gpu`) and `proteinclaw doctor` both need Docker access. Running them from a Claude Code session that started before the group change requires the `sg docker -c 'bash -c ...'` wrapper. The next session (or a fresh tmux/SSH) won't need it.

### Tool wrappers (4-file convention)

(RFdiffusion3, ProteinMPNN, ESMFold, AF2-multimer — including dep pins, weight-download quirks, parameter footguns.)

#### 2026-05-23 — Tool name regex allows `_`-prefixed tool part
**Context:** PLAN.md §1.7 specifies the smoke tool name as `debug._smoke` (with underscore). My first registry regex was `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$` which rejected the leading underscore.
**Fix:** Loosened to `^[a-z][a-z0-9_]*\.[a-z_][a-z0-9_]*$` (`src/proteinclaw/tools/__init__.py:_NAME_RE`).
**Why it matters:** Internal/test tools live under a leading-underscore directory (e.g., `tools/_smoke/`) to signal "not user-facing." The tool *name* should match that convention. Categories themselves still must start with a letter.

#### 2026-05-23 — Container entrypoint shim must run as host UID/GID
**Context:** LocalRunner mounts the host workspace into the container. By default Docker containers run as root, so files written to `/workspace` would be root-owned on the host, breaking subsequent reads.
**Fix:** `docker run -u $(id -u):$(id -g) ...` (built into `build_docker_run_argv`). Tool Dockerfiles must NOT set `USER` to anything restrictive that would block reading `/app/tool_entrypoint.py` as the host UID.
**Why it matters:** Any future GPU tool that sets `USER appuser` in its Dockerfile will fail at runtime because the bind-mounted entrypoint won't be readable. Spell this out when writing the real model Dockerfiles in Tasks 2–5.

### Plain-Python tools

(UniProt, PDB, RCSB, Semantic Scholar, DuckDuckGo — API quirks, rate limits, fixture recipes.)

_No entries yet._

### Agent core & skill file

(Gemini loop, sandbox, `proteindesign.md` behavioral notes, trace format.)

_No entries yet._

### Runner / router

(Docker dispatch, VRAM checks, session workspace layout.)

_No entries yet._

### Persistence & reporting

(SQLite schema migrations, report.html quirks.)

_No entries yet._

### Cross-cutting / process

(Decisions about workflow, testing strategy, doc structure that future sessions should respect.)

#### 2026-05-23 — Phase 1 landed
**Context:** PLAN.md Task 1.1–1.7 implemented end-to-end. Result envelope, 4-file tool convention, registry, auto-discovery, ComputeRouter, LocalRunner, doctor, and the `debug._smoke` smoke tool all in place.
**State:** 64 non-GPU unit tests pass. The single GPU smoke test (`tests/tools/_smoke/test_smoke.py`, `@pytest.mark.gpu`) passes end-to-end on the A100 (~22s including the first-time Docker build). `proteinclaw doctor` returns all-green and writes `~/.proteinclaw/doctor_ok`.
**Honesty about implementation state:**
- `proteinclaw run` / `history` / `show` / `cancel` are intentional stubs that exit 2 with "NOT YET IMPLEMENTED — lands in Phase X." Do not interpret their presence as a working pipeline.
- The agent core, sandbox, Gemini integration, and any real model wrapper are NOT in this phase — they land in Tasks 2–8.
- The Docker build for the smoke tool is uncached on first run; cached subsequently. No optimisation done.
**Why it matters:** Task 1 was the unblocker for every other phase. Future tool tasks add one directory under `src/proteinclaw/tools/<name>/` and rely on the dispatch path proven here.
**Links:** Phase 1 commit (TBD).

#### 2026-05-23 — NOTES.md created
**Context:** Project still in Phase 0; PRD, ARCHITECTURE, PLAN, README, CLAUDE all written. No source code yet.
**Decision:** This file is the canonical cross-session notebook. Every future Claude Code session (and every agent in this repo) is expected to read it at session start and append to it when surfacing anything non-obvious. CLAUDE.md updated to require this.
**Why it matters:** Without it, each new session has to re-derive every gotcha from git log + code reading, which is slow and lossy.
**Links:** `CLAUDE.md` "Session memory" section.
