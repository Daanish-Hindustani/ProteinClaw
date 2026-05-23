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

#### 2026-05-23 — Phases 2 + 3 landed (uniprot, pdb, rcsb, literature, web)
**Context:** All 5 plain-Python tools registered via `@registry.register` and auto-imported by `tools/__init__.py:bootstrap_default_tools`. 103 mocked unit tests + 6 `@pytest.mark.live` E2E tests all pass.
**Sharing layer:** `tools/_http.py` (User-Agent + timeouts) and `tools/_paths.py` (session_workspace + per-host cache dir). New plain-Python tools should reuse these — don't roll your own `requests` setup.
**Why it matters:** These tools are the agent's eyes (target resolution, sequence lookup, literature). Phase 5's agent loop wires them into the Gemini system prompt via `registry.describe_for_planner()`.
**Links:** Phase 2+3 commit (TBD).

#### 2026-05-23 — UniProt `recommendedName.fullName.value` is the formal name, NOT aliases
**Context:** Live test for human PD-L1 (Q9NZQ7) expected to find "PD-L1" in the protein name. The actual formal name is "Programmed cell death 1 ligand 1". Aliases (PD-L1, PDCD1, B7-H1) live under `proteinDescription.alternativeNames` / `cdantNames` — currently NOT extracted.
**Decision (deferred):** v1 returns the formal name only. If the agent needs alias matching, extend `_entry_to_summary` in `uniprot.py` to include `aliases: list[str]` from `alternativeNames`.
**Why it matters:** Agent prompts that say "look up PD-L1" will get back "Programmed cell death 1 ligand 1" — Gemini handles the synonym just fine, but if a future caller relies on exact string match, this is a footgun.

#### 2026-05-23 — PDB TER record filter required per-chain check, not just "in_kept_chain" flag
**Context:** First version of `pdb.py:_filter_pdb` kept TER records whenever a kept ATOM had just been emitted. That accidentally emitted the TER for a *discarded* chain (because the previous kept chain set the flag).
**Fix:** `if chain is None or _line_chain(line) == chain: out.append(line)` — match TER by its own chain id (column 22), not by trailing-state flag.
**Why it matters:** Naive readers (PyMOL, some Biopython parsers) treat a stray TER as a chain break and silently mis-identify residue ranges downstream. The smoke test would have hidden this — only a 2-chain fixture catches it.

#### 2026-05-23 — Semantic Scholar rate-limit hits on the *first* call from a fresh box
**Context:** Live E2E run hit HTTP 429 on the first literature_search call from this VM (PD-L1 binder design query). Tool degraded per PRD §10.2: returned `{rate_limited: true, results: []}`, no error envelope.
**Decision:** Behavior is *correct as specified* — agent proceeds without literature input. But if you're debugging the tool itself and need real results, either:
1. Add an `x-api-key` header by registering for the Semantic Scholar API key program (free), or
2. Wait ~5 min and retry.
**Why it matters:** Don't interpret a 429 in CI as a tool bug. The `rate_limited: true` flag in the envelope is the canonical signal.

#### 2026-05-23 — DDG HTML scrape: stay with regex parser, no bs4
**Context:** Considered adding `beautifulsoup4` for `web.py`'s HTML fallback. Rejected: DDG's HTML view (`html.duckduckgo.com/html/`) returns predictable `<a class="result__a">`/`<a class="result__snippet">` pairs that a 2-line regex handles fine, and saves a 3-MB dep + transitive parser engine.
**Validated:** As of 2026-05-23 the regex returns clean results for a real RFdiffusion-related query (3/3 hits relevant). The endpoint expects a `POST` with form-encoded `q=` (not GET).
**Decision (revisit):** If DDG restructures, prefer adding `bs4` as an *optional* dep, not hard. The scrape is a fallback to a fallback; it's allowed to break.
**Why it matters:** Saves dependency churn and keeps web.py inspectable in a single screen.

#### 2026-05-23 — RCSB Search API: `result_set` field, not `result`
**Context:** RCSB Search API docs are spread across https://search.rcsb.org/. The response key is `result_set` (with underscore), not `results`. Sort order is by `score desc` by default; we override the *final* ranking with a resolution+recency+search-score blend so a higher-rated old structure can lose to a 2025 sub-2Å structure.
**Decision:** Per-entry metadata (resolution, deposition_date, structure_method, title) is fetched in a second pass via the Data API (`https://data.rcsb.org/rest/v1/core/entry/{id}`). For >5 candidates this is wasteful; if it shows up as a bottleneck, parallelise with `concurrent.futures` or fetch a single batched query via the GraphQL endpoint.
**Why it matters:** Saves the next reader from re-discovering the per-entry fetch chain.

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

#### 2026-05-23 — Phases 2 + 3 landed (data + research plain-Python tools)
**Context:** PLAN.md Task 6.1–6.5 implemented and E2E-verified against live APIs.
**State:** 103 mocked unit tests + 6 live tests pass. Demo run against the canonical PD-L1 workflow shows the full data flow:
- `rcsb_search("PD-L1 IgV domain")` → 3 ranked candidates, top = 6NOJ (2.33Å, 2019)
- `pdb_fetch("5JDS", chain="A", crop="18-134")` → 921 atoms / 115 residues written to session workspace
- `uniprot_fetch("Q9NZQ7")` → 290 aa human PD-L1 with both Ig-like domains annotated
- `literature_search("PD-L1 binder de novo design")` → 429 rate-limit, gracefully degraded (rate_limited:true, no error)
- `web_search("RFdiffusion hotspot residue tips")` → 3 high-quality HTML results
**Honesty:** No agent, no Gemini calls, no sandbox, no model wrappers. `proteinclaw run` is still a stub. Tasks 2–5 (PLAN.md numbering — the model wrappers) and Task 7 (sandbox) and Task 8 (agent core) remain.
**Links:** Phase 2+3 commit (TBD).

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
