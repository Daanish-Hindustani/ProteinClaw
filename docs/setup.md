# Setup

## Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv)

## Install

```bash
uv sync --extra dev
```

## Run checks

```bash
uv run ruff check src tests
uv run mypy
uv run pytest
```

## Real protein-design tools (optional, Phase 6)

RFdiffusion3, ProteinMPNN, and AlphaFold require GPU + conda environments and are excluded from the default install. Conda env files and instructions land here in Phase 6.
