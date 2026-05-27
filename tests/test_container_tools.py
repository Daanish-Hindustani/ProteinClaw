"""Task 1.3 — auto-discovery of tool.yaml directories."""

from __future__ import annotations

from pathlib import Path

import pytest

from proteinclaw.tools import ToolRegistry
from proteinclaw.tools._container_tools import (
    ToolManifestError,
    discover_tools,
    parse_manifest,
)

_GOOD_YAML = """
name: design.example
display_name: Example
category: design
description: A small example tool.
parameters:
  type: object
  additionalProperties: false
  properties:
    n:
      type: integer
  required: [n]
compute:
  requires_gpu: true
  min_vram_gb: 8
  gpu_profile: small
execution:
  docker_image: example/example:0.1.0
  timeout_s: 120
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    p = d / "tool.yaml"
    p.write_text(content)
    return p


def test_parse_manifest_valid(tmp_path: Path) -> None:
    path = _write(tmp_path, "example", _GOOD_YAML)
    tool = parse_manifest(path)
    assert tool.name == "design.example"
    assert tool.requires_gpu is True
    assert tool.min_vram_gb == 8
    assert tool.docker_image == "example/example:0.1.0"
    assert tool.tool_dir == str(path.parent.resolve())


def test_parse_manifest_missing_key_loud(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "example",
        "name: design.x\ndisplay_name: x\ncategory: design\nparameters: {type: object}\n",
    )  # no description
    with pytest.raises(ToolManifestError, match="missing required key 'description'"):
        parse_manifest(path)


def test_parse_manifest_bad_yaml_loud(tmp_path: Path) -> None:
    path = _write(tmp_path, "example", "::: not yaml :::")
    with pytest.raises(ToolManifestError, match="invalid YAML"):
        parse_manifest(path)


def test_parse_manifest_gpu_requires_vram(tmp_path: Path) -> None:
    bad = _GOOD_YAML.replace("min_vram_gb: 8", "min_vram_gb: 0")
    path = _write(tmp_path, "example", bad)
    with pytest.raises(ToolManifestError, match="min_vram_gb"):
        parse_manifest(path)


def test_parse_manifest_gpu_requires_image(tmp_path: Path) -> None:
    bad = _GOOD_YAML.replace("docker_image: example/example:0.1.0", "docker_image: ''")
    path = _write(tmp_path, "example", bad)
    with pytest.raises(ToolManifestError, match="docker_image"):
        parse_manifest(path)


def test_parse_manifest_bad_json_schema(tmp_path: Path) -> None:
    bad = _GOOD_YAML.replace("type: integer", "type: not-real-type")
    path = _write(tmp_path, "example", bad)
    with pytest.raises(ToolManifestError, match="invalid JSON Schema"):
        parse_manifest(path)


def test_discover_tools_uses_passed_registry(tmp_path: Path) -> None:
    _write(tmp_path, "alpha", _GOOD_YAML.replace("design.example", "design.alpha"))
    _write(tmp_path, "beta", _GOOD_YAML.replace("design.example", "design.beta"))
    reg = ToolRegistry()
    discovered = discover_tools(tmp_path, registry=reg)
    names = sorted(t.name for t in discovered)
    assert names == ["design.alpha", "design.beta"]
    assert "design.alpha" in reg and "design.beta" in reg


def test_discover_tools_raises_on_malformed_member(tmp_path: Path) -> None:
    _write(tmp_path, "good", _GOOD_YAML)
    _write(tmp_path, "bad", "::: invalid :::")
    reg = ToolRegistry()
    with pytest.raises(ToolManifestError):
        discover_tools(tmp_path, registry=reg)


def test_bundled_smoke_tool_manifest_parses() -> None:
    """The packaged tools/_smoke/tool.yaml must always be parseable."""
    smoke_yaml = Path(__file__).resolve().parents[1] / "src/proteinclaw/tools/_smoke/tool.yaml"
    assert smoke_yaml.exists()
    tool = parse_manifest(smoke_yaml)
    assert tool.name == "debug._smoke"
    assert tool.requires_gpu is True
