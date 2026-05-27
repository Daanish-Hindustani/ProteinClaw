# PLAN.md — `proteinclaw` Implementation Plan

**Source of truth:** `PRD-proteinclaw.md` v1.0.0 + `CLAUDE.md`.
**Build order is normative.** Task 1 unblocks all other model/tool work; Task 8 depends on Tasks 2–7; Tasks 10–11 depend on 8–9.

Each task below is a **small, independently mergeable unit**. Per `CLAUDE.md` ("Keep changes modular and tested"), if a task feels too large to land as one PR, split it along the listed subcomponents — every subcomponent has its own tests, success criteria, and manual-test recipe.

Workflow for every task: **Plan → Design → Test (RED) → Implement (GREEN) → Manual test → Code review → Update docs** (CLAUDE.md "Development workflow").

---

## Task 1 — Tool wrapper skeleton, registry, runner, router, `doctor`

**Why first:** Every other tool depends on this. Land it end-to-end with one trivial GPU tool to prove the dispatch path before writing any real model wrapper.

### 1.1 Repo scaffolding + packaging

**Implementation**
- Create `src/proteinclaw/` package layout per PRD §9.1 (empty modules ok).
- `pyproject.toml` with `proteinclaw` package, console script `proteinclaw = proteinclaw.cli:main`, deps pinned (click/typer, pyyaml, jsonschema, biopython, numpy, requests, restrictedpython, claude-agent-sdk).
- `tests/` mirror layout. `pytest` config with `gpu` marker registered + skipped by default (`-m "not gpu"`).

**Tests**
- `tests/test_package.py`: `import proteinclaw` succeeds; `proteinclaw --version` works.
- `pytest` collects with no errors.

**Success criteria**
- `pip install -e .` installs cleanly; `proteinclaw --help` prints usage.
- `pytest -m "not gpu"` passes with 0 tests of substance and 0 errors.

**Manual test**
- Fresh venv → `pip install -e .` → `proteinclaw --help` → `proteinclaw --version`.

---

### 1.2 `Tool` dataclass + `ToolRegistry` + `@register`

**Implementation** (`src/proteinclaw/tools/__init__.py`)
- `Tool` dataclass: `name, display_name, description, category, parameters (JSON Schema dict), requires_gpu, min_vram_gb, gpu_profile, docker_image, timeout_s, function`.
- `ToolRegistry` with `register(...)` decorator and `get_tool(name)`, `list_tools(category=None)`, `describe_for_planner() -> str` (formats tool list for system prompt).
- Singleton `registry`.
- `parameters` validated against JSON Schema on registration (fail fast if a tool ships a bad schema).

**Tests**
- Register a fake plain-Python tool; `registry.get_tool("test.fake")` returns it.
- Bad JSON Schema in `parameters` raises at registration time.
- Duplicate `name` raises.
- `describe_for_planner()` includes name, description, and JSON Schema example.

**Success criteria**
- 100% unit coverage on registry. No GPU needed.

**Manual test**
- `python -c "from proteinclaw.tools import registry; print(registry.describe_for_planner())"`.

---

### 1.3 `_container_tools.py` — auto-discovery

**Implementation**
- At import, walks `src/proteinclaw/tools/*/tool.yaml`. For each, validates required fields (PRD §9.2), validates `parameters` is a JSON Schema, registers a **placeholder function** (router intercepts; placeholder must never execute — raise `RuntimeError("dispatch bypassed router")` if called directly).
- Fail loudly on malformed `tool.yaml` — never silently skip a tool dir.

**Tests**
- Fixture: temp dir with one valid `tool.yaml` → tool registered.
- Fixture: malformed YAML → raises with file path in message.
- Fixture: tool.yaml missing `compute.min_vram_gb` for `requires_gpu: true` → raises.

**Success criteria**
- Adding a directory with a valid `tool.yaml` registers it without code changes elsewhere.

**Manual test**
- Drop a hand-written `tool.yaml` in `src/proteinclaw/tools/_smoke/` → restart Python → `registry.get_tool(...)` finds it.

---

### 1.4 `ComputeRouter` (`runner/router.py`)

**Implementation**
- `route(tool, **kwargs) -> dict`.
- If `not tool.requires_gpu`: call `tool.function(**kwargs)` in-process.
- Else: GPU detection via `nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits` (cached for session); compare to `tool.min_vram_gb`. If insufficient or missing → return `{"summary": "Error: GPU unavailable or below floor", "error": "compute_unavailable"}`. Else delegate to `LocalRunner.run(tool, **kwargs)`.

**Tests**
- Mock `nvidia-smi` → returns 24000 MB → route passes through.
- Mock `nvidia-smi` → returns 8000 MB for a 24 GB tool → returns structured error.
- Mock `nvidia-smi` missing → structured error, no exception.
- Plain-Python tool goes direct, not through `LocalRunner`.

**Success criteria**
- All errors are structured dicts; no exception leaves `route()`.

**Manual test**
- On a non-GPU machine, run `python -c "from proteinclaw.runner.router import ComputeRouter; print(ComputeRouter().route(<gpu tool>, ...))"` → expect structured error.

---

### 1.5 `LocalRunner` (`runner/local.py`)

**Implementation**
- `run(tool, **kwargs) -> dict`.
- Generate / accept `session_id` (UUID4 hex); create `~/.proteinclaw/gpu-workspace/<session_id>/`.
- Write `input.json` with kwargs.
- `docker images` check; if image missing, `docker build` from the tool's directory.
- `docker run --gpus all -v <workspace>:/workspace -v <weight caches per PRD §9.6> -e INPUT_FILE=/workspace/input.json -e OUTPUT_FILE=/workspace/output.json -e SESSION_ID=<session_id> <image>`.
- Enforce `tool.timeout_s` via `subprocess.run(timeout=...)`.
- Read `output.json`; on container nonzero exit, return `{"summary": "Error: container exited <code>", "error": stderr_tail, "metrics": {...}}`.

**Tests**
- Mock `subprocess.run` to simulate docker — verify command construction (mount flags, env vars, image, timeout).
- Container nonzero exit → structured error.
- Container timeout → structured error.
- Missing image → triggers `docker build` from tool dir.

**Success criteria**
- Every failure path returns a dict; no exception escapes `run()`.
- Workspace mount path is exactly `~/.proteinclaw/gpu-workspace/<session_id>/`.

**Manual test (requires Docker + GPU)**
- Use the §1.7 smoke tool to round-trip JSON in/out of a container.

---

### 1.6 `proteinclaw doctor`

**Implementation** (`src/proteinclaw/cli.py`)
- Checks per PRD §10 (GPU present, VRAM ≥ floor, Docker, NVIDIA Container Toolkit, free disk ≥200 GB, network reachability, Claude authentication present, weight caches). The Claude auth check distinguishes the subscription path (`~/.claude/.credentials.json` OAuth, no `ANTHROPIC_API_KEY` in env) from the API path (`ANTHROPIC_API_KEY` set) and WARNs if both are set (API key silently preempts OAuth → subscription bypassed).
- `--self-test` runs `pytest -m gpu tests/tools/`.
- Non-zero exit if any of 1–4, 7 fail.
- `proteinclaw run` checks a `.proteinclaw/doctor_ok` marker (written by a successful `doctor`) and refuses to run otherwise.

**Tests**
- Each check is a pure function returning `(ok: bool, message: str)` and is unit-tested with mocks (no real `nvidia-smi` / `docker info` calls).
- Aggregator returns correct exit code given a mix of pass/warn/fail.

**Success criteria**
- `proteinclaw doctor` prints a clear pass/warn/fail table.
- Refuses `proteinclaw run` until doctor passes.

**Manual test**
- Run on dev machine; capture output; confirm GPU/Docker/disk lines match `nvidia-smi` / `df -h`.

---

### 1.7 Smoke GPU tool — `tools/_smoke/`

**Implementation**
- Trivial GPU "tool" with the full 4-file layout. `implementation.run()` shells `nvidia-smi --query-gpu=memory.used,memory.total --format=csv` and returns `{"summary": "smoke ok", "vram": ..., "metrics": {...}}`.
- Dockerfile: `nvidia/cuda:12.1.0-base-ubuntu22.04` + `python3`.

**Tests** (`tests/tools/_smoke/test_smoke.py`, `@pytest.mark.gpu`)
- `LocalRunner.run(smoke_tool)` → returns dict with `summary == "smoke ok"` and a numeric `vram_total_mb`.

**Success criteria**
- End-to-end dispatch (registry → router → runner → container → result envelope) proven on a real GPU box.

**Manual test**
- `python -c "from proteinclaw.tools import registry; from proteinclaw.runner.router import ComputeRouter; print(ComputeRouter().route(registry.get_tool('debug._smoke'), session_id='manual'))"`.

---

## Task 2 — ProteinMPNN tool (`tools/proteinmpnn/`)

**Implementation**
- 4 files per PRD §9.2. Port from `celltype-agent` with §9.10 deviations applied:
  - Expose `sampling_temp` as a real parameter (don't hardcode 0.1).
  - Bump subprocess timeout to match `tool.yaml execution.timeout_s` (300s).
  - Add `fix_positions` / `chain_id` for binder workflows (keep target chain frozen).
- `normalize_args()` separate from `run()`; raises `ValueError` on bad input.
- Output: write FASTA files to `/workspace/proteinmpnn_<step>/`; return paths in envelope plus `sequences: List[str]`, `scores: List[float]`.
- VRAM monitor thread (use shared `_gpu_metrics` module — see Task 3.x).

**Tests** (`tests/tools/proteinmpnn/`, `@pytest.mark.gpu`)
- Fixture: tiny backbone PDB (~50 residues). Run end-to-end through `LocalRunner`.
- Assertions: `len(sequences) == num_sequences`, every score in `[0.0, 5.0]`, all sequences are valid amino acids, FASTA file exists at returned path.
- Unit test (no GPU): `normalize_args()` rejects malformed input (negative `num_sequences`, bad `chain_id`, missing `backbone_pdb`).

**Success criteria**
- Tool runs on a 24 GB GPU within 300s for a 50-residue backbone with 8 sequences.
- VRAM peak < 12 GB (matches `min_vram_gb`).
- No bytes in JSON envelope; all artifacts are paths.

**Manual test**
- `proteinclaw doctor --self-test` includes `tests/tools/proteinmpnn/`.
- Sanity: invoke `ComputeRouter().route(...)` directly with a fixture backbone and inspect the FASTA written to `/workspace/...`.

---

## Task 3 — ESMFold tool (`tools/esmfold/`)

### 3.1 Shared `_gpu_metrics` module

**Implementation**
- Pull the VRAM monitor thread + `_vram_mb()` helper into `src/proteinclaw/tools/_gpu_metrics.py` (referenced by every GPU tool's `implementation.py`).
- Note: this module ships **inside** the container too — it lives in the package source and gets `COPY`-d in by each Dockerfile.

**Tests**
- Unit test the monitor on a stubbed `_vram_mb` that returns increasing values → `peak` reflects the max.

**Success criteria**
- Single source of truth for VRAM monitoring. Every GPU tool imports it.

---

### 3.2 ESMFold implementation

**Implementation**
- 4 files per §9.2 + §9.10 deviations:
  - **Hoist model load to module scope.** `_MODEL = None`; first call loads and caches.
  - **Batch mode:** `sequences: List[str]` parameter. Loop over batch in-process; one container invocation handles many sequences.
  - **No silent fallback** for missing torch/transformers — return `{"error": "esmfold_libraries_missing"}`.
  - **Enforce max length 1024** in `normalize_args`.
  - Keep the HF-helper → manual PDB extraction fallback (defensive against `transformers` drift).
- Output: per-sequence `{pdb_path, confidence (monomer pLDDT), num_residues}` list, plus aggregate `metrics`.

**Tests** (`tests/tools/esmfold/`, `@pytest.mark.gpu`)
- Fixture: 3 short sequences (~40-residue toy peptides) → batch run.
- Assertions: 3 PDB paths exist, each `confidence` in `[0, 100]`, model loaded once (verify via a counter or log).
- Unit test: `normalize_args` rejects sequences > 1024 and non-AA characters.
- Library-missing test: monkeypatch `torch` import to fail → expect `error: esmfold_libraries_missing` (not a stub PDB).

**Success criteria**
- Second sequence in a batch is materially faster than the first (proves model cache works).
- No silent fallback path remains in the code.

**Manual test**
- Invoke with the canonical short test peptide; visualize the returned PDB in PyMOL/Mol*; confirm `confidence > 50` for a well-folded peptide.

---

## Task 4 — RFdiffusion3 tool (`tools/rfdiffusion3/`)

**Implementation**
- Write from scratch (no celltype-agent reference uses RFD3). Reuse celltype-agent v1's scaffolding for: `normalize_args()`, `_parse_hotspot_residues()` (enforces `[A-Z]\d+`, validates against declared `receptor_chain`), `_parse_chain_ranges()` (PDB ATOM scan → `{chain: (min_resi, max_resi)}`).
- Refuse host file paths from outside `/workspace` (security boundary).
- Lazy weight download from `http://files.ipd.uw.edu/pub/RFdiffusion3/...` into `~/.cache/rfdiffusion`; magic-byte sanity check (`PK\x03\x04` zip or `\x80` pickle) before reuse.
- **Do not truncate PDB output** (deviation from celltype-agent). Save full PDBs to `/workspace/rfdiffusion3_<step>/`, return paths.
- Hydra-style overrides to `run_inference.py`: `contigmap.contigs`, `ppi.hotspot_res`, `inference.num_designs`, `diffuser.T`.

**Tests** (`tests/tools/rfdiffusion3/`, `@pytest.mark.gpu`)
- Fixture: small target PDB (e.g. trimmed PD-L1 IgV crop, ~120 residues), `binder_length=70`, `hotspot_residues="A54,A57,A61"`, `num_designs=2`.
- Assertions: 2 PDB paths exist; each contains >300 ATOM lines (sanity-check non-empty); paths are inside `/workspace/...`.
- Unit tests (no GPU): hotspot parser rejects `"54,57"` (missing chain), `"a54"` (lowercase), `"A54,B57"` when `receptor_chain="A"`. Chain-range parser handles gaps and chain switches correctly.

**Success criteria**
- Runs on a 24 GB GPU within 600s for 2 designs at length 70.
- Weight cache works: second run with empty `/workspace` but warm `~/.cache/rfdiffusion` does not re-download.

**Manual test**
- Manually craft a small target PDB; run end-to-end; open output PDBs in PyMOL; confirm hotspot residues are contacted by the designed backbone.

---

## Task 5 — AlphaFold2-multimer tool (`tools/alphafold2_multimer/`)

**Implementation**
- 4 files per §9.2 + §9.10 deviations:
  - **Trim YAML** to exactly: `binder_sequence`, `target_sequence`, `relax_prediction` (bool, default false), `msa_source` (`colabfold | single_sequence`, default `colabfold`).
  - Build paired multimer A3M: ColabFold API for each chain, then pair into OpenFold's expected format.
  - **`single_sequence` fallback path:** on ColabFold timeout/error, retry once; on second failure, fall back and log clearly that the run is degraded.
  - Templates off, relaxation off by default.
  - Output parsing: identify binder chain by chain ID (preserved from FASTA order), average B-factors (== pLDDT) over CA atoms of the binder chain → `complex_confidence` (the **ranking signal**).
  - Return: `complex_pdb_path`, `complex_confidence`, `binder_chain`, `target_chain`, `num_residues` dict.
- OpenFold params (~5 GB) downloaded once to `~/.cache/openfold/params/`.
- Multimer only — no `:`-trick monomer mode.

**Tests** (`tests/tools/alphafold2_multimer/`, `@pytest.mark.gpu`)
- Fixture: small known binder/target pair (synthetic or trimmed real case, <250 residues total to fit 24 GB).
- Assertions: complex PDB written; `complex_confidence` in `[0, 100]`; `binder_chain` set; both chains present in output PDB.
- Unit tests (no GPU): `normalize_args` rejects ambiguity codes (`X`, `B`, `Z`) and sequences > 1024 per chain. Verify per-chain B-factor averaging on a hand-built PDB fixture.
- Integration: simulate ColabFold timeout → verify single-sequence fallback kicks in once and logs the degradation.

**Success criteria**
- Runs end-to-end on a 24 GB GPU within `timeout_s` for a small complex.
- The complex pLDDT averaging is over the **binder chain only** (verified by a hand-built fixture where target B-factors are 99 and binder B-factors are 50 → returned `complex_confidence ≈ 50`).

**Manual test**
- Run on a synthetic binder + PD-L1 IgV pair; open output complex in PyMOL; confirm chain IDs and confidence number sanity.

---

## Task 6 — Data tools (`tools/uniprot.py`, `pdb.py`, `rcsb.py`, `literature.py`, `web.py`)

**Why one task, five files:** all plain-Python, all use the same `@register` decorator, all hit external APIs, all use the same result-envelope shape. Land them in one PR — but each file is independent and has its own tests.

### 6.1 `uniprot.py` — `data.uniprot_fetch`

**Implementation**
- `requests` GET to UniProt REST. Accepts UniProt accession or name. Returns `{summary, sequence, domains, accession}`.
- Validate at boundary: bad accession → `{"error": "invalid_query"}`.

**Tests**
- Unit tests with `responses` or `requests_mock` against recorded fixtures (no live HTTP in CI).
- Cases: valid accession → parsed; ambiguous name → returns all candidates with a `requires_clarification: true` flag; HTTP 404 → structured error.

**Success criteria**
- Fully offline-testable. No live API calls in unit tests.

**Manual test**
- `python -c "from proteinclaw.tools.uniprot import uniprot_fetch; print(uniprot_fetch(query='PD-L1'))"`.

---

### 6.2 `pdb.py` — `data.pdb_fetch`

**Implementation**
- RCSB Data API + file service. Download `.pdb` by ID, save to `~/.cache/proteinclaw/pdb/<id>.pdb`, return path.
- Optional `chain` and `crop` (residue range) — produce a cropped sub-PDB also.

**Tests**
- Mock RCSB; assert file written, path returned, crop arithmetic correct.
- 404 → structured error (no AlphaFold DB fallback in v1 — PRD §6.4).

**Success criteria**
- Two consecutive calls hit cache (not network) for the second.

**Manual test**
- Fetch `5JDS` chain A crop `54-150`; open the cropped file in PyMOL.

---

### 6.3 `rcsb.py` — `data.rcsb_search`

**Implementation**
- RCSB Search API. Natural-language query → list of candidate entries with resolution, deposition date, chains, domain annotations. The **primary entry point for target resolution** (PRD §6.4).
- Rank: prefer high resolution, complete chain, recent deposition, presence of named domain.

**Tests**
- Recorded fixtures for "PD-L1 IgV", "human PD-L1", and an intentionally ambiguous "p53".
- Assert ranking order; assert ambiguous queries return ≥2 entries flagged for clarification.

**Success criteria**
- For "PD-L1 IgV" returns at least one structure with the IgV domain in the metadata.

**Manual test**
- Live call for "PD-L1"; inspect ranking.

---

### 6.4 `literature.py` — `research.literature_search`

**Implementation**
- Semantic Scholar Graph API; bioRxiv fallback. Client-side throttling (token bucket).
- On rate-limit: return `{"summary": "rate-limited", "results": []}`, **don't fail the run** (PRD §6.2).
- Cache per-session at `/workspace/literature_<step>/results.json`.

**Tests**
- Mock 429 → throttle → eventual success.
- Mock both APIs down → returns empty results, no exception.

**Success criteria**
- Quota-aware; never throws.

**Manual test**
- Search "PD-L1 binder design"; inspect results.

---

### 6.5 `web.py` — `research.web_search`

**Implementation**
- DuckDuckGo Instant Answer + HTML scrape (no API key).
- On scrape failure: return `{"summary": "web search unavailable", "results": []}`.

**Tests**
- Mocked HTML; mocked failure mode; assert graceful degradation.

**Success criteria**
- Never throws; degrades cleanly.

**Manual test**
- `web_search(query="RFdiffusion3 binder hotspot tips")` → reasonable results or empty list.

---

## Task 7 — RestrictedPython sandbox + `sandbox_exec`

**Implementation**
- Configure RestrictedPython per PRD §6.2:
  - Allow: `json, re, math, os.path, pathlib (read-only), collections, Bio (Biopython), numpy`, plus registered tool functions injected by name.
  - Block: arbitrary file writes outside the run's `output-dir`; raw `subprocess`/`os.system`; non-tool network; `eval`/`exec` on non-sandboxed code; imports outside allowlist.
- `sandbox_exec` tool: takes a Python string + bindings, returns last-expression value or a structured error.

**Tests**
- Escape attempts (all must fail with a structured error, never silently succeed):
  - `import subprocess` → blocked.
  - `open("/etc/passwd")` → blocked.
  - `__import__("os").system("ls")` → blocked.
  - Writing outside `output-dir` → blocked.
  - `eval("...")` → blocked.
- Allowed: reading a PDB from `/workspace`, parsing with Biopython, computing a checksum, returning a dict.

**Success criteria**
- All 5 escape tests pass (blocked). All 1 allowed test passes (works).
- No exception escapes `sandbox_exec`; bad code → `{"error": "...", "traceback": "..."}`.

**Manual test**
- Drop into a Python REPL → run an attacking snippet via `sandbox_exec` → confirm blocked.

---

## Task 8 — Agent core + skill file loader

**Depends on:** Tasks 2–7 (need tool descriptions to build the planner prompt).

### 8.1 Skill loader

**Implementation**
- `src/proteinclaw/agent/skills.py`: read `src/proteinclaw/skills/proteindesign.md` from disk; return its contents as a string. **Not lazy-loaded** — called once per run at agent init.

**Tests**
- Unit: returns file contents verbatim; missing file → loud error (no silent empty string).

**Success criteria**
- Editing `proteindesign.md` changes agent behavior in the next run with no code changes.

**Manual test**
- Add a unique sentinel string to `proteindesign.md`; run agent in `--dry-run`; verify the sentinel appears in the logged system prompt.

---

### 8.2 Claude Agent SDK loop

**Implementation** (`src/proteinclaw/agent/core.py`)
- `claude_agent_sdk.ClaudeSDKClient` (or `query()` for one-shot runs). Model picked from config (default `claude-opus-4-7`; Sonnet/Haiku also fine).
- System prompt assembly: `system_prompt={"type": "preset", "preset": "claude_code", "append": <proteindesign.md contents + registry.describe_for_planner()>}`.
- Tools: wrap every registered tool in `@tool` decorators bundled into a single in-process MCP server via `create_sdk_mcp_server(name="proteinclaw_tools", ...)`. Each `@tool` body just calls `ComputeRouter.route(...)` so GPU dispatch is uniform.
- Autonomous mode: `permission_mode="bypassPermissions"`. Pre-allowlist tool prefixes via `allowed_tools=["mcp__proteinclaw_tools__*"]`.
- Stream the SDK's tool-call events into `trace.jsonl` (role, content, tool, tool_args, tool_result_summary, timestamp).
- `--show-reasoning` mirrors those events to stdout.

**Tests**
- Mock the SDK client (or use the SDK's own test harness); simulate a 3-turn loop with 2 tool calls; verify `trace.jsonl` has 3 rows, tool calls dispatched through router, final answer returned.
- Tool error from router → agent receives the error envelope (not an exception); test agent can react and retry.

**Success criteria**
- The trace is sufficient to reconstruct what the agent did (PRD §7 auditability).

**Manual test**
- Run with `--dry-run` on the canonical PD-L1 prompt; inspect the planned tool sequence in stdout.

---

### 8.3 First version of `proteindesign.md`

**Implementation**
- Write the skill file per PRD §6.3: which tool for what task, the ESM→AF2 cascade (agent decides ESMFold threshold), the ranking signal (binder-chain pLDDT), I/O schemas, default hyperparams, recovery patterns, literature-search prompts.

**Tests**
- Snapshot test: file exists, contains markers for each required section.

**Success criteria**
- A researcher reading only `proteindesign.md` can predict what the agent will do.

**Manual test**
- Code review of the skill file by someone other than the author.

---

## Task 9 — SQLite persistence + `history` / `show`

**Implementation**
- Schema per PRD §6.9 — three tables: `runs`, `designs`, `agent_steps`. **Do not** denormalize top pLDDT — derive from `designs.plddt_af2_complex`.
- `src/proteinclaw/db.py`: `init_db(path)`, `record_run(...)`, `record_design(...)`, `record_step(...)`, `list_runs(limit, target)`, `get_run(run_id)`.
- Schema migration on `proteinclaw upgrade` (single `schema_version` table; idempotent).
- CLI: `proteinclaw history [--limit N] [--target X]` (tabular), `proteinclaw show <run_id>` (open `report.html`).

**Tests**
- In-memory SQLite; insert + read round-trip for all three tables.
- Migration: blank DB → applied → schema_version bumps.
- `list_runs` filter by `target` exact match.

**Success criteria**
- 80%+ coverage; all CRUD paths covered.

**Manual test**
- Run `proteinclaw run --dry-run` twice; `proteinclaw history --limit 5` shows both.

---

## Task 10 — Pipeline orchestration + target resolution + iteration

**Depends on:** 8, 9, all tool tasks.

### 10.1 Target resolution

**Implementation**
- Encoded in `proteindesign.md`, executed by the agent via `rcsb` → `uniprot` → `pdb`.
- If multiple distinct biological entities match → agent emits one clarifying question with a numbered menu (the **only** allowed interactive interruption per PRD §6.1).
- On RCSB miss → fail fast with the agent's full reasoning. No AlphaFold DB fallback.

**Tests**
- Mocked tool stack: unambiguous target → resolves to a PDB; ambiguous target → produces clarifying question; no hit → structured failure with reasoning.

**Success criteria**
- Single interactive prompt at most; no mid-run prompts ever.

**Manual test**
- Run with prompt "PD-L1 IgV" (unambiguous) → resolves automatically.
- Run with prompt "p53" (ambiguous) → one clarifying menu.
- Run with prompt for a non-existent target → fails clearly.

---

### 10.2 Campaign loop + ESM→AF2 cascade

**Implementation**
- `src/proteinclaw/agent/campaign.py`: orchestrates `rfdiffusion3` → `proteinmpnn` → `esmfold` → `alphafold2_multimer`.
- Agent picks ESMFold discard threshold per round and logs it (PRD §6.3).
- Top-K by `complex_confidence` (binder-chain pLDDT). Default K=10.
- Enforce `--max-designs` cap across the campaign.

**Tests**
- Mocked tools returning canned outputs; assert correct ordering, threshold logging, top-K selection.
- Test that monomer pLDDT and complex pLDDT are stored separately (both surfaced in report).

**Success criteria**
- Ranking is by **AF2 complex pLDDT over binder chain**, never by ESM monomer pLDDT (PRD §6.6).

**Manual test**
- Run end-to-end on the canonical PD-L1 prompt with `--max-designs 8 --rounds 1` on a GPU box. Inspect `designs/` and the top of the ranking.

---

### 10.3 `--rounds N` iteration

**Implementation**
- After round 1, agent reviews results, decides on a refinement pass (narrower length, different temp, focused hotspots). Decision logged.
- `--rounds 1` disables iteration; `--rounds >2` permitted up to user budget.

**Tests**
- Mocked tool stack; round 2 receives narrower parameters derived from round 1 results.

**Success criteria**
- Iteration is the agent's call (not hardcoded). Reasoning visible in `trace.jsonl`.

**Manual test**
- `--rounds 2` on PD-L1; inspect round 2 plan to see how it differed from round 1.

---

## Task 11 — Report generation

**Implementation**
- `src/proteinclaw/report.py`: single self-contained `report.html` with:
  - Ranking table (rank, design ID, ESM monomer pLDDT, AF2 complex pLDDT, sequence preview).
  - ESM vs AF2 scatter plot (highlights designs that fold but don't dock).
  - 3D viewer (Mol* or NGL, CDN-loaded for now).
  - Optional reasoning panel (gated on `--show-reasoning`, sourced from `trace.jsonl`).
- No external assets beyond CDN; works fully offline once cached.

**Tests**
- Snapshot test: feed canned designs → assert HTML contains all design IDs, both pLDDT columns, the scatter data, and (when enabled) the reasoning panel.
- HTML validates (basic well-formedness check).

**Success criteria**
- Opens in a browser without errors; 3D viewer loads on the top design's PDB.

**Manual test**
- Open a generated `report.html` in Chrome. Click into a design. Verify the 3D viewer renders; verify the scatter plot is interactive.

---

## Task 12 — Polish & docs

**Implementation**
- README: install, `proteinclaw doctor`, canonical PD-L1 example, troubleshooting (OOM, missing weights, ColabFold timeouts, Docker permission errors).
- `proteinclaw doctor` UX: human-friendly pass/warn/fail table; actionable next steps per failure.
- Error messages audited end-to-end — every error path returns a structured envelope with `summary` and `error` (PRD §9.3).
- `CLAUDE.md` reviewed; refresh `proteindesign.md` if agent behavior changed across tasks.

**Tests**
- Doc snippets are run-as-examples in CI where possible (e.g., `proteinclaw --help` output matches a fixture).
- `pytest -m "not gpu"` passes on fresh checkout.

**Success criteria**
- Researcher unfamiliar with the codebase can install, doctor-green, run the PD-L1 example, get a report — without editing any config (PRD §11 success criterion #1).

**Manual test**
- Fresh checkout on a clean machine → follow the README → reach `report.html`.

---

## Cross-cutting requirements (apply to every task)

These come straight from `CLAUDE.md`. Failing any of them means the task is not done.

- **4-file-per-tool convention** is mandatory for every GPU model; non-negotiable (PRD §9.2, CLAUDE.md "Conventions").
- **Session-keyed workspace**: tools write artifacts to `/workspace/<tool>_<step>/` and return **paths**, never PDB bytes in the JSON envelope (PRD §9.3).
- **Uniform result envelope**: `{summary, metrics, ...tool-specific}` on success; `{summary: "Error: ...", error, metrics}` on failure. No exception leaves a `run()` (PRD §9.3, §9.7).
- **Fail fast, no silent fallbacks** — except the three explicitly allowed: literature-search rate-limit, DuckDuckGo scrape failure, ColabFold single-sequence fallback (which is logged loudly).
- **One concern per change** — a new tool wrapper, a router fix, and a CLI flag are three changes, not one (CLAUDE.md "Keep changes modular and tested").
- **Tests live next to the code** — plain-Python tools get unit tests beside them; GPU tools get `@pytest.mark.gpu` integration tests beside them.
- **Honesty about implementation state** — report stubs as stubs, OOM ceilings as OOM ceilings, untested paths as untested. Bias toward under-claiming (CLAUDE.md "Honesty about implementation state").
- **Debug loop** — when something breaks: failing test first, web-search before guessing on unknown errors, append a dated entry to `DEBUG.md`, fix root cause not symptom (CLAUDE.md "Debug workflow").

---

## Dependency graph (quick reference)

```
Task 1 ──► Task 2 ─┐
       │           │
       ├► Task 3 ──┤
       │           │
       ├► Task 4 ──┼──► Task 8 ──► Task 10 ──► Task 11 ──► Task 12
       │           │
       ├► Task 5 ──┤
       │           │
       ├► Task 6 ──┤
       │           │
       └► Task 7 ──┘
                   │
       Task 9 ─────┘
```

Tasks 2–7 are independent after Task 1 lands and can be parallelized. Task 9 is independent of the tool tasks and can also be done in parallel after Task 1.
