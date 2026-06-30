# Contributing

ProteinClaw is a Codex plugin and MCP server for protein binder design
workflows. Contributions should keep the package small, testable, and safe to
install as a plugin.

## Development Setup

```bash
uv sync --extra dev
uv run --extra dev ruff check .
uv run --extra dev pytest -m "not gpu and not live"
```

The lint gate uses Ruff for Pyflakes plus serious pycodestyle errors. The default
test suite must not require network access, live APIs, Docker, or a GPU. Mark
tests that need those resources with `live` or `gpu`.

## Plugin Validation

Run Codex plugin validation before opening a pull request:

```bash
uv run python /Users/daanishhindustano/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

Skill files must have valid YAML frontmatter. Plugin metadata must not contain
placeholders.

## Pull Requests

Pull requests should:

- Keep changes focused.
- Include tests for behavior changes.
- Avoid committing generated runs, reports, logs, caches, or local workspaces.
- Update `README.md`, `docs/ARCHITECTURE.md`, or `CHANGELOG.md` when public
  behavior changes.
- Preserve the Codex-only plugin contract unless a separate Claude plugin effort
  is explicitly in scope.

## Scientific and Safety Expectations

ProteinClaw outputs are computational candidates. Do not present generated
sequences, structures, metrics, or reports as experimentally validated results.
Document assumptions, limitations, and validation status clearly.
