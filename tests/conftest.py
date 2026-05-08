"""Test-session defaults.

CLI/production runs default to real backends (`PROTEINCLAW_BACKEND=auto`),
which would hit live REST APIs and require GPU installs. Tests must stay
offline and deterministic, so we force the global default to `mock` for
the entire test session and clear any per-tool overrides leaking in from
the developer's shell.

Individual tests that exercise the factory's swap logic (
``tests/tools/test_factory.py``) use `monkeypatch.setenv(...)` to set
specific values, which take precedence over this session-wide default.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

_TOOL_VARS = (
    "PROTEINCLAW_RCSB_BACKEND",
    "PROTEINCLAW_FOLDSEEK_BACKEND",
    "PROTEINCLAW_ALPHAFOLD_BACKEND",
    "PROTEINCLAW_RFDIFFUSION_BACKEND",
    "PROTEINCLAW_PROTEIN_MPNN_BACKEND",
)


@pytest.fixture(autouse=True)
def _force_mock_backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin tests to mock backends unless a test explicitly overrides.

    Runs before every test. Sets the global `PROTEINCLAW_BACKEND=mock` and
    clears per-tool overrides — `monkeypatch` rolls both back at teardown
    so tests stay isolated.
    """
    monkeypatch.setenv("PROTEINCLAW_BACKEND", "mock")
    for var in _TOOL_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
