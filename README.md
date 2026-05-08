# ProteinClaw

Agentic protein-design workflow with branching sub-agents, LLM-driven tool calling, evaluation, memory, and self-evolution.

**Status:** Phases 0–6.5 complete. Real protein-design tools wired (RCSB / Foldseek / ESM Atlas REST + RFdiffusion / ProteinMPNN / ColabFold local). The CLI runs end-to-end with Claude as the planner and tool-calling sub-agent. Phase 7 (Evolution Service) is paused. See [`PLAN.md`](PLAN.md) for the full roadmap and [`PROJECT.md`](PROJECT.md) for the component spec.

---

## Install

Requires Python 3.11+ and [`uv`](https://github.com/astral-sh/uv).

```bash
git clone <repo-url>
cd ProteinClaw
uv sync --extra dev
```

That's enough to run the test suite and the CLI in mock mode. Real tools require additional setup (below).

---

## Run a real prompt

### One-time setup

```bash
uv run proteinclaw setup
```

The wizard asks for your Anthropic API key (or reuses `ANTHROPIC_API_KEY` from your shell), then asks whether to install the local GPU tools. Answer *no* when developing on a laptop; *yes* on a Lambda Labs box (it shells out to `scripts/lambda_labs_setup.sh` after gating on Linux + GPU + ≥ 50 GB free disk).

Config is persisted to `~/.config/proteinclaw/config.json` (chmod 600).

### Health check

```bash
uv run proteinclaw doctor
```

Reports OS, NVIDIA driver, Python version, `uv`, ProteinClaw config, install paths, free disk. Exit code is non-zero if anything blocking is missing.

### One-shot prompt

```bash
uv run proteinclaw run --prompt "Design a binder for PDB 1ABC"
```

Output:
- Session id
- Per-task: verdict, winner branch id, passed metrics, summary critique
- Path to the SQLite trace (`~/.local/share/proteinclaw/state/traces.db`) for replay

### Interactive REPL

```bash
uv run proteinclaw run -i
```

```
proteinclaw> Design a binder for 1ABC
[ ok ] task #1: verdict=stop_success winner=… passed_metrics=['plddt', 'ptm'] iterations=1
   Branch passed 2/2 criteria; recommended next step: stop_success.

proteinclaw> Pick hotspots on 1ABC then design a binder against them
…

proteinclaw> /quit
```

`/quit`, `quit`, `exit`, or Ctrl-D ends the session. Errors don't kill the REPL — you can keep going after a failure.

### Backend modes

The CLI is honest about what it's running. `PROTEINCLAW_BACKEND` controls the global default:

```bash
# Everything mocked — fast iteration, no network, no GPU.
PROTEINCLAW_BACKEND=mock uv run proteinclaw run --prompt "…"

# Auto (default after setup) — REST where possible, local install where required.
uv run proteinclaw run --prompt "…"

# Mock just the GPU-only tools while running the rest live:
PROTEINCLAW_RFDIFFUSION_BACKEND=mock PROTEINCLAW_PROTEIN_MPNN_BACKEND=mock \
  uv run proteinclaw run --prompt "…"
```

See [`docs/setup.md`](docs/setup.md) for the full env-var table.

---

## Lambda Labs (GPU end-to-end)

For the real RFdiffusion / ProteinMPNN / ColabFold pipeline you need a Linux GPU box. The full guide is in [`docs/lambda_labs.md`](docs/lambda_labs.md). Short version:

```bash
# On a fresh Lambda Labs Ubuntu 22.04 GPU instance:
git clone <repo-url> ~/persistent/proteinclaw
cd ~/persistent/proteinclaw
./scripts/lambda_labs_setup.sh                 # ~30–60 min on first run
echo 'source ~/.proteinclaw_env' >> ~/.bashrc
source ~/.proteinclaw_env

# Manual per-tool smoke tests:
./scripts/smoke_test.sh                        # interactive walk-through

# Then drive ProteinClaw end-to-end:
uv run proteinclaw setup                       # answer "yes" to install when prompted
uv run proteinclaw run --prompt "Design a binder for 1ABC"
```

The setup script downloads ~10 GB of RFdiffusion weights with HTTPS + MD5 verification, builds three conda envs (RFdiffusion / ProteinMPNN / ColabFold), and writes `~/.proteinclaw_env` with all the env-var pointers.

---

## Test

```bash
# Default: mocks + LLM stubs, no network, no GPU. ~1.5s.
uv run pytest

# Lint + type:
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy

# Live-tool tests (require setup; no tests carry the marker today,
# but the marker is honoured):
uv run pytest -m expensive
```

The test suite holds 336 tests (≥ 80% coverage gate; currently 88.75%). `tests/conftest.py` pins `PROTEINCLAW_BACKEND=mock` for the entire session so CI never hits external services.

### What each test layer proves

| Layer | Run | What it proves |
|---|---|---|
| Unit | `uv run pytest tests/<area>` | Each component (registry, evaluator, memory, planner, sub-agent…) works in isolation against stubs |
| Integration | `uv run pytest tests/orchestrator/test_orchestrator_integration.py -v` | Orchestrator drives Planner → BranchingService → SubAgent → Evaluator end-to-end with mocked tools |
| Manual / GPU | `./scripts/smoke_test.sh` on a GPU box | RFdiffusion / ProteinMPNN actually load weights and produce real outputs |
| End-to-end + LLM | `proteinclaw run -i` on a configured box | Real Claude plans + drives tools; designs land in the trace store |

---

## Reading a trace

Every session writes to `~/.local/share/proteinclaw/state/traces.db` (SQLite + FTS5). Quick replay:

```python
import asyncio
from proteinclaw.memory.trace_store import SQLiteTraceStore

store = SQLiteTraceStore("/home/<you>/.local/share/proteinclaw/state/traces.db")
events = asyncio.run(store.read_session("<session-id>"))
for e in events:
    print(e.kind.value, e.component, e.payload)
```

Or full-text search:

```python
asyncio.run(store.search("rfdiffusion", session_id="<session-id>"))
```

See [`docs/trace-format.md`](docs/trace-format.md) for the canonical event kinds.

---

## Documentation

| Doc | Purpose |
|---|---|
| [`PROJECT.md`](PROJECT.md) | Component spec + 8-stage workflow (authoritative on architecture) |
| [`PLAN.md`](PLAN.md) | Phased implementation roadmap |
| [`CLAUDE.md`](CLAUDE.md) | Conventions + commands for Claude Code sessions |
| [`docs/setup.md`](docs/setup.md) | Backend selection, env vars, local install |
| [`docs/lambda_labs.md`](docs/lambda_labs.md) | GPU instance setup + manual smoke tests |
| [`docs/skill-format.md`](docs/skill-format.md) | Skill schema + validation |
| [`docs/eval-metrics.md`](docs/eval-metrics.md) | Evaluation metrics + verdict policy |
| [`docs/trace-format.md`](docs/trace-format.md) | TraceEvent shape + canonical event kinds |
| [`docs/memory-format.md`](docs/memory-format.md) | SQLite + FTS5 schemas |
| [`docs/tool-registry-format.md`](docs/tool-registry-format.md) | Tool registry surface + adding new tools |

---

## CLI reference

```text
proteinclaw --help                       Top-level help
proteinclaw --version                    Version string

proteinclaw setup                        Interactive first-run wizard
proteinclaw doctor                       System probe (exits non-zero on FAIL)
proteinclaw run --prompt "…"             One-shot prompt
proteinclaw run -i, --interactive        REPL mode
```

Setup state lives at `~/.config/proteinclaw/config.json` (XDG). Per-session SQLite databases live at `~/.local/share/proteinclaw/state/`.
