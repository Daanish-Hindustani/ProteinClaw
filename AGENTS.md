# Agent Notes — Protein Design Fork

Guidance for AI assistants working in this repo. This is a focused fork of Nous Research's Hermes Agent, stripped to support **protein design** workflows.

## What this codebase is

- A CLI agent (`cli.py`, `run_agent.py`) that exposes protein-design tools to an LLM via tool-calling.
- A custom plugin at `plugins/protein-design/` providing tools for PubMed, UniProt, RCSB, RFdiffusion3, ProteinMPNN, ESMFold, AlphaFold2-Multimer, binder design, Rosetta interface analysis, and structure inspection.
- A curated skills directory at `skills/protein-design/` with skill documents for each tool/workflow.

## What was removed from upstream Hermes

When working in this repo, do **not** reach for these — they are gone:

- All messaging-platform integrations (Telegram, Discord, Slack, WhatsApp, Signal, Feishu, Matrix, etc.) and `gateway/platforms/`
- Voice mode, TTS, transcription, NeuTTS samples
- Vision/image-analysis tools and image-generation tools
- Smart-home (Home Assistant), Spotify, Yuanbao, send_message, xAI HTTP clients
- The Docusaurus website (`website/`), `web/` UI, `ui-tui/`, `tui_gateway/`, dashboard plugins
- All non-protein skills and `optional-skills/`

If you see lazy `from tools.voice_mode import …` or `from tools.vision_tools import …` blocks inside `cli.py` or `run_agent.py`, those are dead branches sitting behind `_voice_mode` flags. Do not call paths that hit them. They will be removed in a follow-up surgery.

## Repo map (kept)

- `plugins/protein-design/` — the focus of this fork
- `plugins/{context_engine,memory,observability}` — general-purpose runtime plugins, kept
- `tools/` — core Hermes tools (browser, terminal, file, mcp, code execution, web, registry)
- `agent/` — adapters, prompt builders, memory manager, trajectory tracking
- `gateway/` — local CLI gateway (platforms stripped)
- `hermes_cli/` — CLI commands, auth, config
- `environments/` — tool execution environments (local, docker, modal, etc.)
- `skills/protein-design/` — skill documents

## Working principles

- Treat protein-design tools, skills, and plugin code as the high-touch surface. Other Hermes core code is upstream-derived; prefer minimal edits there.
- Do not re-introduce platform integrations, voice, vision, or image-gen.
- Tests live under `tests/`. Many platform-specific tests were removed; if you add new tests, prefer protein-design-relevant flows.
- Default model selection and runtime config live in `hermes_cli/config.py` and `cli-config.yaml.example`.

## Useful tasks

- Smoke-test imports: `python3 -c "import toolsets, model_tools, mcp_serve"`
- List available toolsets: `python3 toolsets.py`
- Run the CLI: `python cli.py` or `./proteinclaw` (legacy `./hermes` wrapper still works)
- Run protein-design tests: `pytest tests/ -k protein`

## Rollback

`backup/pre-protein-prune` branch holds the pre-prune state. `git reset --hard backup/pre-protein-prune` restores everything.
