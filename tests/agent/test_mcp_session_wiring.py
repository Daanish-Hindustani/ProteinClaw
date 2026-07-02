"""MCP wrapper — session_id injection + host→container path translation."""

from __future__ import annotations

from pathlib import Path

from proteinclaw.agent.mcp_tools import (
    _accepts_param,
    _translate_host_path_to_workspace,
)
from proteinclaw.tools import Tool


def test_translate_host_path_replaces_prefix() -> None:
    ws = Path("/home/u/.proteinclaw/gpu-workspace/sess_xyz")
    out = _translate_host_path_to_workspace(
        f"{ws}/pdb_fetch_0/5JDS.pdb", ws
    )
    assert out == "/workspace/pdb_fetch_0/5JDS.pdb"


def test_translate_root_path() -> None:
    ws = Path("/home/u/.proteinclaw/gpu-workspace/sess_xyz")
    assert _translate_host_path_to_workspace(str(ws), ws) == "/workspace"


def test_translate_passthrough_non_workspace() -> None:
    ws = Path("/home/u/.proteinclaw/gpu-workspace/sess_xyz")
    assert _translate_host_path_to_workspace("/some/other/path", ws) == "/some/other/path"


def test_translate_handles_symlinked_workspace(tmp_path: Path) -> None:
    """Regression for the 2026-05-25 symlink bug: ~/.proteinclaw is a symlink
    (SETUP §2 persistent FS). LocalRunner resolves the workspace, so tool
    envelopes carry the real path; if host_workspace is the un-resolved
    symlinked spelling the prefix wouldn't match and the rewrite would silently
    skip (GPU tool then rejects the path). The rewrite must resolve and match.
    """
    real = tmp_path / "nfs" / "gpu-workspace" / "sess1"
    real.mkdir(parents=True)
    (tmp_path / "home").mkdir()
    # ~/.proteinclaw -> persistent FS (the SETUP §2 symlink)
    (tmp_path / "home" / ".proteinclaw").symlink_to(tmp_path / "nfs", target_is_directory=True)
    linked_ws = tmp_path / "home" / ".proteinclaw" / "gpu-workspace" / "sess1"  # symlinked spelling

    # host_workspace = symlinked spelling, value = resolved real path (what
    # LocalRunner puts in envelopes) → must still rewrite to /workspace.
    out = _translate_host_path_to_workspace(f"{real}/rfdiffusion3_0/m0.pdb", linked_ws)
    assert out == "/workspace/rfdiffusion3_0/m0.pdb"


def test_translate_handles_symlinked_value_against_resolved_workspace(tmp_path: Path) -> None:
    real = tmp_path / "nfs" / "gpu-workspace" / "sess1"
    real.mkdir(parents=True)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / ".proteinclaw").symlink_to(tmp_path / "nfs", target_is_directory=True)
    linked_value = tmp_path / "home" / ".proteinclaw" / "gpu-workspace" / "sess1" / "pdb_fetch_0" / "x.pdb"
    linked_value.parent.mkdir(parents=True)
    linked_value.write_text("ATOM\n", encoding="utf-8")

    out = _translate_host_path_to_workspace(str(linked_value), real)
    assert out == "/workspace/pdb_fetch_0/x.pdb"


def test_translate_recurses_into_dicts_and_lists() -> None:
    ws = Path("/home/u/.proteinclaw/gpu-workspace/sess_xyz")
    nested = {
        "target_pdb": f"{ws}/pdb_fetch_0/x.pdb",
        "backbones": [f"{ws}/rfd_0/a.pdb", f"{ws}/rfd_0/b.pdb"],
        "label": "PD-L1",
    }
    out = _translate_host_path_to_workspace(nested, ws)
    assert out["target_pdb"] == "/workspace/pdb_fetch_0/x.pdb"
    assert out["backbones"] == ["/workspace/rfd_0/a.pdb", "/workspace/rfd_0/b.pdb"]
    assert out["label"] == "PD-L1"


def test_translate_no_op_when_workspace_none() -> None:
    """When host_workspace is None, do NOT translate anything (plain-Python tool path)."""
    assert _translate_host_path_to_workspace("/anything", None) == "/anything"


def test_accepts_param_detects_schema_property() -> None:
    schema = {
        "type": "object",
        "properties": {"session_id": {"type": "string"}, "pdb_id": {"type": "string"}},
    }
    pc = Tool(
        name="data.fake",
        display_name="fake",
        description="d",
        category="data",
        parameters=schema,
        function=lambda **_: {},
    )
    assert _accepts_param(pc, "session_id")
    assert _accepts_param(pc, "pdb_id")
    assert not _accepts_param(pc, "nope")
