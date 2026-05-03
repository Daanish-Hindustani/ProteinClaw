# ProteinClaw

A focused conversational agent for protein design.

ProteinClaw is built on top of [Nous Research's Hermes Agent](https://github.com/NousResearch/hermes-agent) runtime: the upstream codebase has been pruned to its core (CLI, planning/memory, tool registry, browser, terminal, code execution, RL scaffolding) and extended with a custom **protein-design plugin**, protein-design-specific skills, and a wizard-onboarding flow that wires those tools up for either local or cloud execution.

## What it does

ProteinClaw gives you a conversational interface over a curated set of protein-design tools:

- **Sequence + literature search** — PubMed, UniProt, RCSB
- **Structure prediction** — ESMFold, AlphaFold2-Multimer
- **Design** — RFdiffusion3, ProteinMPNN, binder design
- **Analysis** — Rosetta interface analyzer, structure inspection

All wired through the Hermes tool-calling runtime, so the agent can plan multi-step pipelines (search → design → predict → analyze) and run them with persistent memory across sessions.

## Onboarding (local vs cloud)

The first run of `proteinclaw setup` walks you through a wizard that includes a **protein-design step**: you choose whether the structure-prediction and design tools should run **locally** (you bring the GPU) or in the **cloud** (managed providers, with the relevant API keys configured up-front).

```bash
./proteinclaw setup     # interactive wizard, including the protein-design step
```

## Quick start

```bash
# Install dependencies (uv recommended)
uv sync

# Run the CLI
python cli.py
# or use the wrapper
./proteinclaw
```

## Repo layout

```
plugins/protein-design/      # Custom protein-design plugin (tools, runtime, schemas)
skills/protein-design/       # Protein-design skill documents
plugins/                     # Kept: context_engine, memory, observability
tools/                       # Core tools (web, terminal, browser, file, mcp, etc.)
agent/                       # LLM adapters, prompt builders, memory manager
gateway/                     # Local CLI gateway (platform integrations stripped)
environments/                # Tool execution environments
hermes_cli/                  # CLI wiring (auth, config, commands, setup wizard)
```

> **Module names:** internal Python modules are still prefixed `hermes_*` to avoid a
> codebase-wide import rename. The user-facing binary and project name is `proteinclaw`.

## What's been removed from upstream Hermes

To focus on protein design, this fork drops:

- All messaging-platform integrations (Telegram, Discord, Slack, WhatsApp, Signal, Feishu, etc.)
- Voice mode, TTS, transcription, and image generation tools
- Vision tools (LLM image analysis)
- Smart-home (Home Assistant), Spotify, and other consumer integrations
- The Docusaurus website and dashboard UIs
- All non-protein skills

## License

MIT, inherited from upstream Hermes Agent. See `LICENSE`.
