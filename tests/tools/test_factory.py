"""Tests for the backend factory + env-var resolution.

The session-wide `conftest._force_mock_backend` fixture pins
`PROTEINCLAW_BACKEND=mock` and clears per-tool vars before each test.
Tests below override one or both via `monkeypatch.setenv` to exercise
specific resolution paths.
"""

from __future__ import annotations

import pytest

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.factory import (
    UnknownBackendError,
    build_default_registry,
    make_alphafold,
    make_foldseek,
    make_protein_mpnn,
    make_rcsb,
    make_rfdiffusion3,
)
from proteinclaw.tools.protein.alphafold import MockFoldBackend
from proteinclaw.tools.protein.foldseek import MockFoldseekBackend
from proteinclaw.tools.protein.protein_mpnn import MockProteinMPNNBackend
from proteinclaw.tools.protein.rcsb import MockRCSBBackend
from proteinclaw.tools.protein.rfdiffusion3 import MockRFDiffusionBackend


def test_session_default_is_mock_via_conftest() -> None:
    """conftest pins PROTEINCLAW_BACKEND=mock; every tool resolves to mock."""
    assert isinstance(make_rcsb()._backend, MockRCSBBackend)  # type: ignore[attr-defined]
    assert isinstance(make_foldseek()._backend, MockFoldseekBackend)  # type: ignore[attr-defined]
    assert isinstance(make_alphafold()._backend, MockFoldBackend)  # type: ignore[attr-defined]
    assert isinstance(make_rfdiffusion3()._backend, MockRFDiffusionBackend)  # type: ignore[attr-defined]
    assert isinstance(make_protein_mpnn()._backend, MockProteinMPNNBackend)  # type: ignore[attr-defined]


def test_auto_default_uses_rest_for_rcsb(monkeypatch: pytest.MonkeyPatch) -> None:
    from proteinclaw.tools.protein._real.rcsb_rest import RcsbRestBackend

    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    assert isinstance(make_rcsb()._backend, RcsbRestBackend)  # type: ignore[attr-defined]


def test_auto_default_uses_rest_for_foldseek(monkeypatch: pytest.MonkeyPatch) -> None:
    from proteinclaw.tools.protein._real.foldseek_rest import FoldseekRestBackend

    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    assert isinstance(make_foldseek()._backend, FoldseekRestBackend)  # type: ignore[attr-defined]


def test_auto_alphafold_picks_esm_atlas_without_colabfold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from proteinclaw.tools.protein._real.esm_atlas import EsmAtlasBackend

    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    monkeypatch.delenv("COLABFOLD_BIN", raising=False)
    assert isinstance(make_alphafold()._backend, EsmAtlasBackend)  # type: ignore[attr-defined]


def test_auto_alphafold_picks_colabfold_when_bin_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from proteinclaw.tools.protein._real.colabfold_local import LocalColabFoldBackend

    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    monkeypatch.setenv("COLABFOLD_BIN", "/usr/local/bin/colabfold_batch")
    assert isinstance(make_alphafold()._backend, LocalColabFoldBackend)  # type: ignore[attr-defined]


def test_auto_rfdiffusion_without_install_raises_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    monkeypatch.delenv("RFDIFFUSION_PATH", raising=False)
    with pytest.raises(ToolExecutionError) as ex:
        make_rfdiffusion3()
    msg = str(ex.value)
    assert "RFDIFFUSION_PATH" in msg
    assert "git clone" in msg


def test_auto_rfdiffusion_with_install_path_uses_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from proteinclaw.tools.protein._real.rfdiffusion3_local import (
        LocalRFDiffusionBackend,
    )

    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    monkeypatch.setenv("RFDIFFUSION_PATH", "/opt/RFdiffusion3")
    assert isinstance(make_rfdiffusion3()._backend, LocalRFDiffusionBackend)  # type: ignore[attr-defined]


def test_auto_protein_mpnn_without_install_raises_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    monkeypatch.delenv("PROTEINMPNN_PATH", raising=False)
    with pytest.raises(ToolExecutionError) as ex:
        make_protein_mpnn()
    msg = str(ex.value)
    assert "PROTEINMPNN_PATH" in msg
    assert "git clone" in msg


def test_auto_protein_mpnn_with_install_path_uses_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from proteinclaw.tools.protein._real.protein_mpnn_local import (
        LocalProteinMPNNBackend,
    )

    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    monkeypatch.setenv("PROTEINMPNN_PATH", "/opt/ProteinMPNN")
    assert isinstance(make_protein_mpnn()._backend, LocalProteinMPNNBackend)  # type: ignore[attr-defined]


def test_per_tool_var_overrides_global(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-tool var wins over the global, even when global is `auto`."""
    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    monkeypatch.setenv("PROTEINCLAW_RCSB_BACKEND", "mock")
    assert isinstance(make_rcsb()._backend, MockRCSBBackend)  # type: ignore[attr-defined]


def test_unknown_backend_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROTEINCLAW_RCSB_BACKEND", "bogus")
    with pytest.raises(UnknownBackendError):
        make_rcsb()


def test_unknown_global_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even the global var is validated per-tool."""
    monkeypatch.setenv("PROTEINCLAW_BACKEND", "garbage")
    with pytest.raises(UnknownBackendError):
        make_rcsb()


def test_build_default_registry_uses_mock_in_tests() -> None:
    """conftest pins mock; the registry should construct without GPU installs."""
    registry = build_default_registry()
    names = {d.name for d in registry.describe_all()}
    assert names == {
        "rcsb",
        "rfdiffusion3",
        "protein_mpnn",
        "alphafold",
        "foldseek",
        "sandbox",
    }


def test_build_default_registry_auto_without_installs_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto + no install paths → registry construction surfaces the install error."""
    monkeypatch.setenv("PROTEINCLAW_BACKEND", "auto")
    monkeypatch.delenv("RFDIFFUSION_PATH", raising=False)
    with pytest.raises(ToolExecutionError):
        build_default_registry()
