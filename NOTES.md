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

#### 2026-05-23 — Phase 5 landed (agent core + skill loader + MCP wiring + trace + `proteinclaw run`)
**Context:** PLAN.md Task 8 (the agent loop). Built `src/proteinclaw/agent/` on the Claude Agent SDK now that auth is OAuth-via-`claude login` (subscription billing). No Gemini, no hand-rolled loop, no RestrictedPython in this layer.
**Layout:**
- `agent/skills.py` — eager loader for `skills/proteindesign.md` (raises if missing/empty; appended to the SDK's default Claude Code system prompt via the `{"type":"preset","preset":"claude_code","append":…}` pattern).
- `agent/mcp_tools.py` — wraps every registered `Tool` from `tools/registry` as one `@tool`-decorated function bundled into a single `create_sdk_mcp_server(name="proteinclaw_tools")`. Name flattening: `design.rfdiffusion3` → `design_rfdiffusion3` (MCP doesn't allow `.`), so the agent sees `mcp__proteinclaw_tools__design_rfdiffusion3`. `skip_debug=True` filters out `debug.*` (e.g. the smoke tool) from the agent's catalogue.
- `agent/trace.py` — append-only JSONL writer with typed helpers (`run_started`, `assistant_text`, `tool_use`, `tool_result`, `run_completed`, `run_failed`). Trims long string values >4k chars so the trace stays inspectable.
- `agent/core.py` — `run_campaign(prompt, output_dir, ...)` driver. Uses `ClaudeSDKClient` (multi-turn, so the ~$0.15 cache-priming cost amortises across the whole campaign). `permission_mode="bypassPermissions"` + `allowed_tools=["mcp__proteinclaw_tools__*"]` for autonomous runs. Streams every Assistant/User/Result message into trace + an optional `on_stream_chunk` callback for `--show-reasoning`.
- `cli.py:run_cmd` no longer stubs out — wired to `run_campaign`. New flags: `--output-dir`, `--max-turns`, `--model`, `--dry-run`, `--show-reasoning`, `--skip-doctor`. Gated by `doctor_ok()` unless `--skip-doctor`.
- `skills/proteindesign.md` — replaced placeholder with a real 7.2k-char v1 skill describing the 8-step pipeline, the canonical tool catalogue, and the "rules" (one tool at a time, paths not bytes, rate-limit ≠ error, no inventing tool names, etc).
**Verified E2E on subscription path (real ClaudeSDKClient + 3 real tool calls):**
- Prompt: "Resolve the target 'PD-L1 IgV' to a single PDB structure and chain. Use data tools only — DO NOT call any design.* or structure.*."
- Result: 4 turns, 3 tool calls, 0 errors, $0.215, 19.7s
- Agent picked **PDB 6NP9** (1.27 Å, isolated IgV V76T) — actually higher resolution than the 5JDS I'd picked manually earlier. Correctly identified Q9NZQ7 / 290 aa / IgV 19-127. Specified chain A crop 18-134 for RFD3 + the full 290-aa UniProt sequence for AF2's `target_sequence`.
- trace.jsonl shape works: `run_started` → `ToolSearch` (SDK's built-in lazy tool loader) → `data.rcsb_search` → `data.uniprot_fetch` → `assistant_text` → `run_completed`. 10 events; each one one line of valid JSON with `type` + `ts` + type-specific fields.
- Run output dir at `/tmp/proteinclaw-e2e/<run_id>/{designs/, plan.md, trace.jsonl}` matches PRD §6.10 layout.
**Tests:** 16 host-side unit tests for the new agent package (skill loader, trace writer, mcp_tools name flattening + server build, RunPaths layout, CLI dry-run, CLI refuses without doctor marker). Total non-GPU suite: 171 tests, all green. No GPU integration test for the agent yet — covered by the manual E2E above.
**Design choices worth flagging:**
- **MCP server holds ALL tools** rather than one server per category. Flat catalogue, simpler `allowed_tools` config, no cross-server context overhead.
- **`bypassPermissions` AND `allowed_tools` set together.** Allowlist documents intent; bypass mode also covers built-in SDK tools (e.g. ToolSearch) that the model uses for lazy loading.
- **No clarification UX in v1.** The PRD allows one mid-run clarifying question for target resolution; v1 skill file tells the agent to make best-guess and log assumptions instead. Phase 6+ can add a clarification marker in the assistant text.
- **No round/iteration loop in v1.** `--rounds` is deferred to PLAN.md Task 10.3; a single run is one pass through the pipeline.
**Cost note from the real E2E run:** $0.215 for 4 turns / 3 tool calls. The `cache_creation_input_tokens: 23145` is the SDK loading the default Claude Code system prompt + tool manifest into the prompt cache once; on subsequent turns within the same `ClaudeSDKClient` session, `cache_read_input_tokens` dominates. So a full campaign with 30-40 turns will cost roughly that base + the per-turn deltas, not 30×$0.22.
**Known gaps / Phase 6+ TODO:**
- No HTML report (Task 11), no SQLite (Task 9), no `--rounds` (Task 10.3), no triage/ranking module that aggregates AF2 complex_confidence across designs (Task 10.2). The agent currently does triage implicitly in its final text reply.
- The agent's final text isn't persisted to a structured `result.json` — only to stdout + the last `assistant_text` event in trace.jsonl. Worth doing in Phase 6.
- `plan.md` is a placeholder (per the file's own header). The intended use is for the agent's initial plan + reflections; we'll wire that when Task 6 (triage/report) lands.
**Links:** Phase 5 commit (TBD).

#### 2026-05-23 — Fix: Claude auth is OAuth (`claude login`), NOT `ANTHROPIC_API_KEY` — superseding the entry below
**Context:** The note below ("Migrated agent backend from Gemini → Claude Agent SDK (subscription-billed)") was WRONG about the auth path. User corrected it with the actual Anthropic docs.
**Correct flow (per [Anthropic support article 15036540](https://support.claude.com/en/articles/15036540) and Claude Code docs):**
1. `claude login` writes OAuth credentials to `~/.claude/.credentials.json` (mode 0600). The Agent SDK reads them automatically — **no API key needed**.
2. The user claims their Agent SDK credit one-time in their Claude.ai plan settings. Each user claims their own; credits cannot be pooled, transferred, or shared.
3. **CRITICAL TRAP:** if `ANTHROPIC_API_KEY` is set in the shell that runs the SDK, the API key **silently takes precedence** over OAuth. Usage then bills against pay-as-you-go API credits, NOT the subscription pool. The user thinks they're on subscription billing; they're actually on API billing.
4. Anthropic prohibits routing third-party users' traffic through a single OAuth-authenticated subscription. The subscription path is **per-individual, local use only**. For shared CI / team automation, use API-key billing explicitly.
**What I changed in code to reflect this:**
- `doctor.py`: `check_anthropic_key` → `check_claude_auth`. Four-state detection:
  - PASS: OAuth only → subscription path active
  - WARN: OAuth + API key both set → API key wins, subscription bypassed (the trap)
  - PASS: API key only → pay-as-you-go API path
  - FAIL: neither → run `claude login` or set ANTHROPIC_API_KEY
  Detection looks for `~/.claude/.credentials.json` (the file `claude login` writes).
- `~/.proteinclaw/config.toml`: removed the `api_key` field entirely. The file is now optional and only used for model selection. NO secret material in proteinclaw config anymore.
- Tests rewritten to cover the four states (test_oauth_only_is_subscription_path, test_oauth_plus_api_key_warns, test_api_key_only_is_api_path, test_no_auth_fails).
- All docs (SETUP §5, README install section, CLAUDE.md, ARCHITECTURE.md §9.4, PRD §10 #7, PLAN.md Task 1.6) rewritten to describe the OAuth-first flow + the WARN trap.
**Why it matters:** Without this fix, the user would have followed our own SETUP.md instructions, generated a Console API key, set `ANTHROPIC_API_KEY=...`, and silently spent API credits while thinking they were on subscription billing. The previous entry below misled in exactly that direction.
**Honesty about the earlier note:** I (or rather a subagent I used to research the SDK) confidently claimed "There is no documented fallback to ~/.claude/ login credentials." That was wrong — the SDK absolutely does read OAuth from `~/.claude/.credentials.json` and that's the canonical subscription path. The subagent's research was stale or misread; verifying against the actual support article would have caught it.
**Links:** Auth-fix commit (TBD).

#### 2026-05-23 — ~~Migrated agent backend from Gemini → Claude Agent SDK (subscription-billed)~~  PARTIALLY WRONG — see correction above
**The "SDK still requires ANTHROPIC_API_KEY" claim in this entry is WRONG. The SDK reads OAuth from `~/.claude/.credentials.json` when no API key is set. See the correction entry directly above.**

~~**Context:** User asked to move billing onto their Claude Pro/Max subscription instead of the Gemini API. Per the Claude Agent SDK docs ([overview](https://code.claude.com/docs/en/agent-sdk/overview), [billing](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)), the SDK still requires `ANTHROPIC_API_KEY` as an auth token, BUT — when that key belongs to an account with a Pro/Max subscription — usage flows against the Agent SDK monthly credit pool ($20 Pro / $100 Max-5x / $200 Max-20x), NOT against a separate pay-as-you-go API balance. No documented way to skip the API-key step entirely.~~
**What changed in code:** `pyproject.toml` dep (`google-generativeai` → `claude-agent-sdk`); `doctor.py:check_gemini_key` → `check_anthropic_key`; `~/.proteinclaw/config.toml` schema (`[gemini]` → `[anthropic]`); CLI/skill-file/PRD/ARCHITECTURE/PLAN/CLAUDE/README/SETUP language all swapped Gemini → Claude.
**What's deferred to Phase 5 (the agent core build):**
- Wire `claude_agent_sdk.ClaudeSDKClient` (or `query()`) with `system_prompt={"type": "preset", "preset": "claude_code", "append": <skill file + tool descriptions>}`.
- Wrap every registered tool with `@tool` decorators inside a single `create_sdk_mcp_server(name="proteinclaw_tools")` in-process MCP server.
- `permission_mode="bypassPermissions"` + `allowed_tools=["mcp__proteinclaw_tools__*"]` for autonomous campaigns.
- Stream SDK tool-call events into `trace.jsonl`.
**Sandbox seam changes:** Previously the PRD positioned RestrictedPython as the agent's primary execution boundary. Now the agent runs via the Claude Agent SDK (separate process, its own permission model); RestrictedPython is downgraded to "for any host-side glue code we still want sandboxed (e.g. `sandbox_exec` parsing snippets)". The PRD/ARCHITECTURE wording was updated to reflect this.
**Why it matters:** Phase 5's whole shape changes — no need to hand-roll an LLM loop, no Gemini-specific function-calling JSON, no token bucket on our side. The SDK provides the loop, tool-call streaming, and permissions. Adding/removing tools is just adding/removing `@tool`-decorated functions.
**Concrete cost warning (worth surfacing to users):** A 1+ hour design campaign with many tool calls can consume a meaningful slice of a Pro plan's monthly Agent SDK credit. Pro = $20, Max-5x = $100, Max-20x = $200. Unused credit does NOT roll over. Overage falls back to standard API rates only if "usage credits" are explicitly enabled.
**Links:** Migration commit (TBD).

#### 2026-05-23 — AF2-multimer wrapper landed (Task 5) — PHASE 4 COMPLETE
**Context:** Last of the four model wrappers. Wraps `colabfold_batch` (ColabFold 1.5.5 + JAX + OpenFold params). Implements the binder-chain pLDDT averaging that is THE ranking signal per PRD §6.6.
**Verified E2E (A100):** 2× ubiquitin (76 aa each), `msa_source=single_sequence`, num_recycle=1, num_models=1. Complete in 51.8s. binder-chain pLDDT 45.4 / target 45.0 (low as expected for single-sequence MSA — real campaigns use `msa_source=colabfold` and get 60-80+ on foldable binders). VRAM peak 2.6 GB.
**Dockerfile pins (load-bearing):**
- Base image: `nvcr.io/nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04`. **MUST be cuDNN 8**, not cuDNN 9 — CUDA 12.4 images only ship cuDNN 9 which jax 0.4.23 + nvidia-cudnn-cu12 reject with `CUDNN_STATUS_INTERNAL_ERROR`.
- `colabfold[alphafold]==1.5.5` — current stable release.
- `jax[cuda12]==0.4.23` — jax 0.4.24+ deprecated `jax.linear_util` to a hard error; both `colabfold.batch` and `haiku._src.dot` import that path. Bumping jax requires bumping ColabFold past 1.5.5.
- `numpy<2` (force-reinstall after jax) — pandas / ABI compat for the dm-haiku/colabfold stack.
- `MPLCONFIGDIR=/tmp/matplotlib` — matplotlib tries to create `/.config/matplotlib` as UID 1000 and fails.
**Implementation choices (per PRD §9.10 + Task 5):**
- Trimmed YAML to exactly the four params PLAN specifies + 2 inference-tuning knobs (num_recycle, num_models).
- MSA fallback chain: `colabfold` → retry once → `single_sequence` with `msa_degraded: True` flag.
- Binder is **always** chain A (first in input FASTA). Target is chain B. Output PDB averaging follows this convention.
- B-factor column (cols 61-66) parsed for per-residue pLDDT — AF2's standard placement.
- `complex_confidence` = mean over binder-chain CA atom B-factors. Top-K by this value = campaign ranking.
**Footguns hit:**
1. CUDA/cuDNN version mismatch (described above).
2. `jax.linear_util` removal (described above).
3. numpy 2 ABI break (same as RFdiffusion — already in pattern).
4. matplotlib `/.config/matplotlib` perm error (env var fix).
**Known limitations:**
- OpenFold params download (~5 GB) happens lazily inside ColabFold on first call. There's no magic-byte check on these — if a partial download leaves a corrupted file, manual cleanup of ~/.cache/openfold is needed.
- Templates path is OFF. PRD §9.10 says templates off; adding them would need additional config.
- Tested only with `single_sequence` MSA in CI to avoid MMseqs2 server dependency. Real ranking runs default to `colabfold` MSA (validated by code path; full integration test on a real binder candidate is reserved for the campaign-level E2E in Phase 6+).
**Phase 4 STATE (all four model wrappers landed and E2E verified on A100):**
- ProteinMPNN: 615 MB VRAM, 15.7s for 4 designs.
- ESMFold: 14.2 GB VRAM, 24.5s for 3-peptide batch (including model load).
- RFdiffusion: 4.2 GB VRAM, 122s for 2 binders.
- AF2-multimer: 2.6 GB VRAM, 51.8s for 2-chain complex.
**Links:** Phase 4 final commit (TBD).

#### 2026-05-23 — RFD3 wrapper landed (Task 4 — pivoted to the real RFD3)
**Context:** Replaces the earlier (now-deleted) `tools/rfdiffusion/` v1 wrapper. RFD3 actually exists at `RosettaCommons/foundry` under `models/rfd3/`, distributed as the `rc-foundry[rfd3]` pip package + `foundry install rfd3` for the checkpoint. The original PRD/PLAN `http://files.ipd.uw.edu/pub/RFdiffusion3/` URL was wrong; the canonical checkpoint URL is `https://files.ipd.uw.edu/pub/rfd3/rfd3_foundry_2025_12_01_remapped.ckpt` (downloaded by `foundry install`).
**Verified E2E (A100):** 2 binders to PD-L1 IgV target (115 residues), 3 hotspots (A56/A115/A123 — same as RFD3's own protein_binder_design.json example). 38.5s, VRAM peak 4.5 GB. 176 CA atoms per design (115 target + 61 binder). PPI-recommended params applied by default (`step_scale=3`, `gamma_0=0.2`, `is_non_loopy=true`).
**Dockerfile choices (load-bearing):**
- Base: `rosettacommons/foundry:slim` (3.4 GB). Their official slim image — already has torch + CUDA + all of rc-foundry's pinned deps. Don't try to roll your own from scratch.
- `HOME=/tmp` + `XDG_CACHE_HOME=/tmp/.cache` so the UID-1000 container can write the on-startup caches that cuequivariance/triton create at import.
- `sed -i ... /app/foundry/.env` to prepend `/cache/rfdiffusion` to the bundled `FOUNDRY_CHECKPOINT_DIRS=` line — dotenv loads this file at runtime and OVERRIDES the process env var, so a plain `ENV FOUNDRY_CHECKPOINT_DIRS=...` in our Dockerfile is silently ignored. Patching the .env file is the only way.
**Output format gotcha:** RFD3 writes `.cif.gz` files (atom14 mmCIF format), one per `model_<idx>`. Downstream tools (ProteinMPNN, ESMFold, AF2) speak PDB only. The wrapper auto-converts each `.cif.gz → .pdb` via biotite (already shipped in the foundry image) and returns BOTH paths in the envelope.
**Hotspot atom selection:** RFD3 wants per-atom hotspots (`select_hotspots: {A56: "CG,OH"}`). Our wrapper accepts per-residue strings ("A56,A115,A123") and defaults each to `"CA,CB"` (Gly → `"CA"` only). Per-residue overrides via the `hotspot_atoms` dict kwarg. The agent (Phase 5) can pass full per-atom maps when it has the structural context.
**Known limitations:**
- Foundry install lookup uses simple file-presence check; doesn't verify checkpoint integrity (no magic-byte or sha256 check).
- Symmetry / partial-diffusion / NA-binder modes not exposed.
- The `.env`-load behavior is brittle — if foundry rev-bumps and changes the .env file structure, the sed pattern may need adjustment.
**Strike-through (was wrong):** ~~The PRD/PLAN's "RFdiffusion3" reference is aspirational; RFdiffusion3 doesn't publicly exist.~~ — corrected by this entry; RFD3 IS real, just lives in the `foundry` monorepo under `models/rfd3/`, not in a standalone `RFdiffusion3/` repo.
**Links:** Phase 4 RFD3 pivot commit (TBD).

#### 2026-05-23 — ~~RFdiffusion v1 wrapper landed (Task 4) — NOT "RFdiffusion3"~~  SUPERSEDED
**Superseded by the RFD3 pivot entry above (2026-05-23 — RFD3 wrapper landed). Keeping the original entry intact for historical context; the v1 wrapper directory `tools/rfdiffusion/` has been deleted.**

~~**Context:** PRD/PLAN both reference "RFdiffusion3" with a weight URL at `http://files.ipd.uw.edu/pub/RFdiffusion3/`. That repo and that URL do NOT exist. RFdiffusion3 is aspirational; the public IPD releases are RFdiffusion v1.x and RFdiffusion2. User chose v1 (battle-tested, widely documented). Implementation lives at `tools/rfdiffusion/` and registers as `design.rfdiffusion`.~~
**Verified E2E (A100):** 2 binders to PD-L1 IgV target (115 residues), 3 hotspots (A54, A57, A115), binder length 60-70. 122s, VRAM peak 4.2 GB. Output: 2 full backbone PDBs (182 + 178 CA atoms = target 115 + binder 67/63).
**Dockerfile pins (load-bearing):**
- CUDA 11.6 (nvcr.io/nvidia/cuda:11.6.2-cudnn8-runtime-ubuntu20.04), Python 3.9, torch 1.12.1+cu116, dgl 1.0.2+cu116, e3nn 0.3.3, hydra-core 1.3.2, the bundled `env/SE3Transformer`. Newer torch/dgl combos break the SE3Transformer setup.py. Do NOT modernize.
- `numpy<2` pin — without it, the post-numpy-2 install breaks torch 1.12's ABI.
**Footguns hit (all fixed in Dockerfile / implementation):**
1. Hydra creates `outputs/<date>/<time>/` in CWD. Inside the container CWD defaults to /app/RFdiffusion (root-owned). Fix: pass `hydra.run.dir=.`, `hydra.output_subdir=null`, `hydra.job_logging.handlers.file.filename=/dev/null`; subprocess cwd = session out_folder.
2. RFdiffusion creates `<package_install_path>/../schedules/` on first checkpoint load. UID 1000 can't write to /usr/local/lib/... Fix: `mkdir -p /usr/local/lib/python3.9/dist-packages/schedules && chmod 777` in Dockerfile.
**Lazy weight download:** `Complex_base_ckpt.pt` (~500 MB) into `/cache/rfdiffusion` (bind-mounted to ~/.cache/rfdiffusion on host) on first call. Magic-byte check (`PK\x03\x04` ZIP) on cached file before reuse.
**Contigs string:** `[<target_chain><min>-<max>/0 <binder_lo>-<binder_hi>]` — built dynamically from the target PDB's chain range. The PDB parser in `_normalize.py` scans ATOM records and validates target_chain exists + hotspots are within range.
**Known limitations:**
- Only Complex_base_ckpt + Base_ckpt are lazy-downloaded. ActiveSite, InpaintSeq, Fold-conditioning checkpoints are NOT — uncommon configs need to wget the others into ~/.cache/rfdiffusion manually.
- `partial_T` / `scaffold_guided` modes are not exposed via the tool API. Add when needed.
**Links:** Phase 4 RFdiffusion commit (TBD).

#### 2026-05-23 — ESMFold wrapper landed (Task 3)
**Context:** Second model wrapper. Uses `facebook/esmfold_v1` via HuggingFace `transformers`. Module-scope `_MODEL`/`_TOKENIZER` cache + `_load_model()` makes batch calls amortise the load.
**Verified E2E (A100):** 3-peptide batch — ubiquitin 77.4, insulin A 70.6, poly-A 53.0 (sanity contrast works). VRAM peak 14.2 GB (under 16 GB floor). 24.5s total (20.5s model load + 4s inference). Output PDBs at `<session>/esmfold_0/NNN_<prefix>.pdb`.
**Footguns hit:**
- `torch >= 2.6` required by `transformers` (CVE-2025-32434) — pin in Dockerfile: `torch==2.6.0` on `cu124` wheels. Older torch versions raise on `model.from_pretrained()` regardless of weights_only setting.
- Container UID/GID + `/root/.cache/...` mounts → PermissionError. Fixed by switching all weight cache mounts to `/cache/<name>` (see below).
**Design notes:**
- `output_to_pdb` on `EsmForProteinFolding` returns PDB string per batch entry — no biotite needed.
- `output.plddt` has shape `(batch, seq_len, 37 atoms)`; per-residue pLDDT = `.mean(dim=-1)`; monomer pLDDT = `.mean()` × 100.
- `model.esm = model.esm.float()` for fp32 ESM submodule (numerical stability); trunk runs mixed precision. Standard HF pattern.
**Known limitation:** no chunked/streaming inference for very long sequences (>1024 rejected at normalize). `chunk_size=64` default; can lower if OOM on long seqs in future.
**Links:** Phase 4 ESMFold commit (TBD).

#### 2026-05-23 — Switched weight-cache mount targets from /root/.cache/* to /cache/*
**Context:** LocalRunner runs containers with `-u $(id -u):$(id -g)` for safe workspace file ownership. ESMFold's HuggingFace cache (lock files, partial downloads) needs to be writable by the host UID. `/root/...` is owned by `root` inside the container and not writable by UID 1000.
**Fix:** `WEIGHT_CACHE_MOUNTS` now mounts at `/cache/<name>`. Each tool's Dockerfile sets its own env var (`HF_HOME=/cache/huggingface`, etc.) and `RUN mkdir -p /cache/<name>` so the bind-mount target exists with right perms.
**Why it matters:** Every future model tool that uses a writable cache (transformers HF, rfdiffusion weight downloads, OpenFold params) must set its env vars to the `/cache/<subdir>` path. Document in tool guide / NOTES.

#### 2026-05-23 — Module name collisions across tools (`_normalize.py`) broke test isolation
**Context:** Each tool ships its own `_normalize.py` in its dir. Host-side tests used `sys.path.insert(0, TOOL_DIR)` + `from _normalize import ...`. Running multiple tools' tests in one pytest session = module cache returns the first-loaded one regardless of tool.
**Fix:** Per-test `importlib.util.spec_from_file_location(<unique-name>, path)` so each tool's `_normalize` lives under a unique module name (`_normalize_mpnn`, `_normalize_esm`, ...). Tool source unchanged; only test setup changes.
**Why it matters:** This pattern needs to be in every new model wrapper's test file. The next contributor adding `tools/foo/_normalize.py` should follow the importlib pattern, not `sys.path.insert`.

#### 2026-05-23 — ProteinMPNN wrapper landed (Task 2)
**Context:** First model wrapper — proves the 4-file convention works against a real GPU model. Pulls `github.com/dauparas/ProteinMPNN` head + bundled vanilla weights into the image (180 MB total). torch 2.4.1 with cu121 wheels on a CUDA 12.4 runtime base (forward-compat, well-tested).
**Verified:** E2E on the cached PD-L1 IgV crop (115 residues, chain A) — 4 sequences in 15.7s, VRAM peak 615 MB, avg score 0.914. Designed-chain freezing works via `--pdb_path_chains` (`chain_id` kwarg maps directly).
**Design choices:**
- `normalize_args()` extracted to `_normalize.py` (separate file) so host-side unit tests can import it without triggering container-only `_gpu_metrics` import.
- `fix_positions` parameter is **NOT** implemented in v1. Adding it requires the JSONL helper-script chain (`make_fixed_positions_dict.py` etc.). Document as a known limitation; revisit when binder workflows need it.
- Output paths returned in the envelope are translated host paths (via new `LocalRunner._translate_workspace_paths`). The `summary` string still embeds the in-container `/workspace/...` form — acceptable cosmetic inconsistency.
**Why it matters:** Sets the pattern for ESMFold, RFD3, AF2. Each subsequent tool follows: tool.yaml + Dockerfile (CUDA 12.4 base + torch cu121) + implementation.py (imports `_gpu_metrics.VramMonitor` from /app, normalizes via `_normalize.py`).
**Links:** Phase 4 ProteinMPNN commit (TBD).

#### 2026-05-23 — LocalRunner now stages a build context with shared package files
**Context:** GPU tools need `_gpu_metrics.py` (VRAM monitor, used by every model wrapper). Putting a copy in each tool dir = DRY violation. Docker `COPY ../_gpu_metrics.py` doesn't work (no path-traversal in build context).
**Fix:** `LocalRunner._ensure_image` now creates a tempdir, copies the tool dir + `_SHARED_BUILD_FILES` (currently `["_gpu_metrics.py"]`) into it, then builds from the tempdir. Each tool's Dockerfile can `COPY _gpu_metrics.py /app/` and it Just Works. Tool-local files win on name collision.
**Why it matters:** New shared helpers (e.g., a future MSA cache utility for AF2) just need to be added to `_SHARED_BUILD_FILES`; no per-tool Dockerfile change.

#### 2026-05-23 — LocalRunner translates `/workspace/...` paths in the result envelope to host paths
**Context:** Tools running inside containers know paths as `/workspace/...`. Callers on the host need absolute host paths. Returning the in-container path caused the first E2E test to fail at `Path("/workspace/...").exists()`.
**Fix:** `LocalRunner._translate_workspace_paths` recursively walks the result envelope and rewrites any string starting with `/workspace/` to `<host_workspace>/<rest>`. Applied after parsing `output.json`.
**Why it matters:** Tools don't need to know host paths. Callers don't need to translate. The seam stays narrow (PRD §6 "narrow seams").

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

(Claude Agent SDK loop, in-process MCP server, sandbox, `proteindesign.md` behavioral notes, trace format.)

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
