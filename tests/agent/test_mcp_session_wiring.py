"""MCP wrapper — session_id injection + host→container path translation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
