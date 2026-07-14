"""Container wrapper for a small, hypothesis-driven BoltzGen VHH round."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

_SCAFFOLDS = [
    "/opt/boltzgen/example/nanobody_scaffolds/7eow.yaml",
    "/opt/boltzgen/example/nanobody_scaffolds/7xl0.yaml",
    "/opt/boltzgen/example/nanobody_scaffolds/gontivimab.yaml",
    "/opt/boltzgen/example/nanobody_scaffolds/isecarosmab.yaml",
    "/opt/boltzgen/example/nanobody_scaffolds/sonelokimab.yaml",
]

_DESIGN_MODES = {"de_novo", "scaffold_redesign"}
_SCAFFOLD_SPEC_SUFFIXES = {".yaml", ".yml"}
_SCAFFOLD_STRUCTURE_SUFFIXES = {".cif", ".mmcif", ".pdb"}
_MAX_SCAFFOLD_INPUT_BYTES = 32 * 1024 * 1024


def _error(summary: str, error: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"summary": summary, "error": error, "metrics": {}}
    if details:
        result["details"] = details
    return result


def _resolve_prepared_target(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    recorded_value = manifest.get("prepared_mmcif_path")
    if not recorded_value:
        raise ValueError("target manifest has no canonical prepared mmCIF")
    recorded = Path(str(recorded_value))
    candidates = [recorded, manifest_path.parent / recorded.name, manifest_path.parent / "prepared_gpcr.cif"]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError("prepared GPCR mmCIF referenced by target manifest was not found")


def _design_spec(
    target: Path,
    chain: str,
    residues: list[int],
    excluded_residues: list[int],
    scaffold_paths: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "entities": [
            {
                "file": {
                    "path": str(target),
                    "include": [{"chain": {"id": chain}}],
                    "binding_types": [
                        {
                            "chain": {
                                "id": chain,
                                "binding": ",".join(map(str, residues)),
                                "not_binding": ",".join(map(str, excluded_residues)),
                            }
                        }
                    ],
                }
            },
            {"file": {"path": scaffold_paths or _SCAFFOLDS}},
        ]
    }


def _workspace_file(
    raw_path: str,
    *,
    field: str,
    workspace_root: Path,
    suffixes: set[str],
) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"{field} is required")
    root = workspace_root.expanduser().resolve()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"{field} must live under {root}")
    if candidate.suffix.lower() not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise ValueError(f"{field} must use one of: {allowed}")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"{field} not found: {candidate}")
    size = candidate.stat().st_size
    if size <= 0 or size > _MAX_SCAFFOLD_INPUT_BYTES:
        raise ValueError(
            f"{field} must be nonempty and no larger than {_MAX_SCAFFOLD_INPUT_BYTES} bytes"
        )
    return candidate


def _chain_entries(raw: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"custom scaffold {field} must be a nonempty list")
    chains: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("chain"), dict):
            raise ValueError(f"custom scaffold {field}[{index}] must contain a chain mapping")
        chain = item["chain"]
        chain_id = chain.get("id")
        if not isinstance(chain_id, str) or not chain_id.strip():
            raise ValueError(f"custom scaffold {field}[{index}] has no chain id")
        chains.append(chain)
    return chains


def _validate_custom_scaffold(
    *,
    scaffold_spec_path: str,
    scaffold_structure_path: str,
    scaffold_reference_id: str,
    manifest: dict[str, Any],
    workspace_root: Path = Path("/workspace"),
) -> tuple[Path, Path, dict[str, Any]]:
    """Validate a provenance-linked BoltzGen VHH scaffold before staging it.

    The caller controls mutable regions through the scaffold YAML's ``design``
    entries. Everything outside those entries remains fixed, which is how a
    known Nb39/NbE framework or motif is preserved during redesign.
    """
    spec_path = _workspace_file(
        scaffold_spec_path,
        field="scaffold_spec_path",
        workspace_root=workspace_root,
        suffixes=_SCAFFOLD_SPEC_SUFFIXES,
    )
    structure_path = _workspace_file(
        scaffold_structure_path,
        field="scaffold_structure_path",
        workspace_root=workspace_root,
        suffixes=_SCAFFOLD_STRUCTURE_SUFFIXES,
    )
    if not isinstance(scaffold_reference_id, str) or not scaffold_reference_id.strip():
        raise ValueError("scaffold_reference_id is required for scaffold_redesign")

    representation = manifest.get("target_representation")
    reference_ids = (
        representation.get("reference_scaffold_ids", [])
        if isinstance(representation, dict)
        else []
    )
    normalized_references = {str(value).strip().casefold() for value in reference_ids}
    if scaffold_reference_id.strip().casefold() not in normalized_references:
        raise ValueError(
            "scaffold_reference_id is not declared in the target manifest's "
            "reference_scaffold_ids"
        )

    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid custom scaffold YAML: {exc}") from exc
    if not isinstance(spec, dict):
        raise ValueError("custom scaffold YAML must be a mapping")
    declared_structure = spec.get("path")
    if not isinstance(declared_structure, str) or not declared_structure.strip():
        raise ValueError("custom scaffold YAML must declare one coordinate path")
    if Path(declared_structure).name != structure_path.name:
        raise ValueError(
            "custom scaffold YAML path basename must match scaffold_structure_path"
        )

    included = _chain_entries(spec.get("include"), field="include")
    designed = _chain_entries(spec.get("design"), field="design")
    included_ids = {str(chain["id"]).strip() for chain in included}
    if len(included_ids) != 1:
        raise ValueError("custom nanobody scaffold must include exactly one chain")
    for index, chain in enumerate(designed):
        if str(chain["id"]).strip() not in included_ids:
            raise ValueError(f"custom scaffold design[{index}] refers to a non-included chain")
        if "res_index" not in chain or not str(chain["res_index"]).strip():
            raise ValueError(f"custom scaffold design[{index}] has no res_index")

    groups = spec.get("structure_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("custom scaffold must declare structure_groups")
    visibilities: set[int] = set()
    for index, item in enumerate(groups):
        if not isinstance(item, dict) or not isinstance(item.get("group"), dict):
            raise ValueError(f"custom scaffold structure_groups[{index}] is invalid")
        group = item["group"]
        if str(group.get("id", "")).strip() not in included_ids:
            raise ValueError(
                f"custom scaffold structure_groups[{index}] refers to a non-included chain"
            )
        try:
            visibilities.add(int(group["visibility"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"custom scaffold structure_groups[{index}] has invalid visibility"
            ) from exc
    if 2 not in visibilities or 0 not in visibilities:
        raise ValueError(
            "custom scaffold must include visibility 2 for movable framework context "
            "and visibility 0 for redesigned regions"
        )

    coordinate_text = structure_path.read_text(encoding="utf-8", errors="replace")
    suffix = structure_path.suffix.lower()
    has_atoms = (
        any(line.startswith(("ATOM  ", "HETATM")) for line in coordinate_text.splitlines())
        if suffix == ".pdb"
        else "_atom_site." in coordinate_text
    )
    if not has_atoms:
        raise ValueError("scaffold_structure_path contains no recognizable atom records")
    return spec_path, structure_path, spec


def _stage_custom_scaffold(
    *,
    out_dir: Path,
    spec_path: Path,
    structure_path: Path,
    spec: dict[str, Any],
) -> tuple[Path, Path]:
    staged_dir = out_dir / "custom_scaffold"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_structure = staged_dir / structure_path.name
    shutil.copy2(structure_path, staged_structure)
    staged_spec = staged_dir / spec_path.name
    staged_payload = dict(spec)
    staged_payload["path"] = str(staged_structure)
    # JSON is valid YAML and gives deterministic, readily auditable staging.
    staged_spec.write_text(json.dumps(staged_payload, indent=2), encoding="utf-8")
    return staged_spec, staged_structure


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    *,
    target_manifest_path: str,
    num_designs: int = 16,
    budget: int = 6,
    reuse: bool = True,
    design_mode: str = "de_novo",
    scaffold_spec_path: str | None = None,
    scaffold_structure_path: str | None = None,
    scaffold_reference_id: str | None = None,
    step: int = 0,
    _workspace_root: str = "/workspace",
    **_: Any,
) -> dict[str, Any]:
    if not 4 <= num_designs <= 64:
        return _error("Error: num_designs must be between 4 and 64", "invalid_args")
    if not 1 <= budget <= min(12, num_designs):
        return _error("Error: budget must be positive and no greater than num_designs or 12", "invalid_args")
    if design_mode not in _DESIGN_MODES:
        return _error(
            f"Error: design_mode must be one of {sorted(_DESIGN_MODES)}",
            "invalid_args",
        )
    custom_values = (scaffold_spec_path, scaffold_structure_path, scaffold_reference_id)
    if design_mode == "de_novo" and any(value is not None for value in custom_values):
        return _error(
            "Error: custom scaffold inputs require design_mode='scaffold_redesign'",
            "invalid_args",
        )
    if design_mode == "scaffold_redesign" and any(not value for value in custom_values):
        return _error(
            "Error: scaffold_redesign requires scaffold_spec_path, "
            "scaffold_structure_path, and scaffold_reference_id",
            "invalid_args",
        )

    manifest_path = Path(target_manifest_path).resolve()
    if not manifest_path.exists():
        return _error(f"Error: target manifest not found: {target_manifest_path}", "invalid_args")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        target = _resolve_prepared_target(manifest_path, manifest)
        if int(manifest.get("schema_version", 0)) < 2:
            raise ValueError("target manifest schema v2 or newer is required")
        if manifest.get("mapping_verified") is not True:
            raise ValueError("canonical author-to-label residue mapping is not verified")
        if manifest.get("topology_verified") is not True:
            raise ValueError("GPCR membrane topology is not verified")
        chain = str(manifest["target_label_chain"])
        residues = [int(v) for v in manifest["binding_residues_label"]]
        excluded_residues = [int(v) for v in manifest["excluded_residues_label"]]
        if not chain or chain == "None":
            raise ValueError("target label chain is missing")
        if len(residues) < 2:
            raise ValueError("at least two mapped binding residues are required")
        if len(excluded_residues) < 2:
            raise ValueError("at least two mapped not-binding residues are required")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return _error(f"Error: invalid target manifest: {exc}", "invalid_args")
    if manifest.get("full_chain_preserved") is not True:
        return _error("Error: target manifest does not certify an intact receptor chain", "invalid_args")

    custom_scaffold: tuple[Path, Path, dict[str, Any]] | None = None
    if design_mode == "scaffold_redesign":
        if int(manifest.get("schema_version", 0)) < 3:
            return _error(
                "Error: scaffold_redesign requires a schema-v3 target manifest",
                "invalid_args",
            )
        try:
            custom_scaffold = _validate_custom_scaffold(
                scaffold_spec_path=str(scaffold_spec_path),
                scaffold_structure_path=str(scaffold_structure_path),
                scaffold_reference_id=str(scaffold_reference_id),
                manifest=manifest,
                workspace_root=Path(_workspace_root),
            )
        except (OSError, ValueError) as exc:
            return _error(f"Error: invalid custom scaffold: {exc}", "invalid_args")

    out_dir = Path(_workspace_root) / f"boltzgen_nanobody_{step}"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_dir = out_dir / "run"
    spec_path = out_dir / "design_spec.yaml"
    scaffold_paths: list[str] | None = None
    staged_scaffold_spec: Path | None = None
    staged_scaffold_structure: Path | None = None
    if custom_scaffold is not None:
        redesign_inputs = {
            "design_mode": design_mode,
            "scaffold_reference_id": scaffold_reference_id,
            "target_manifest_sha256": _sha256(manifest_path),
            "scaffold_spec_source_sha256": _sha256(custom_scaffold[0]),
            "scaffold_structure_source_sha256": _sha256(custom_scaffold[1]),
        }
        redesign_lock_path = out_dir / "redesign_inputs.json"
        if redesign_lock_path.exists():
            try:
                locked_inputs = json.loads(redesign_lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return _error(
                    f"Error: unreadable prior redesign input lock: {exc}",
                    "invalid_args",
                )
            if locked_inputs != redesign_inputs:
                return _error(
                    "Error: redesign inputs changed for an existing step; use a new step "
                    "instead of reusing stale BoltzGen results",
                    "invalid_args",
                )
        else:
            redesign_lock_path.write_text(
                json.dumps(redesign_inputs, indent=2),
                encoding="utf-8",
            )
        staged_scaffold_spec, staged_scaffold_structure = _stage_custom_scaffold(
            out_dir=out_dir,
            spec_path=custom_scaffold[0],
            structure_path=custom_scaffold[1],
            spec=custom_scaffold[2],
        )
        scaffold_paths = [str(staged_scaffold_spec)]
    # JSON is valid YAML and avoids a second serializer dependency in the wrapper.
    spec_path.write_text(
        json.dumps(
            _design_spec(
                target,
                chain,
                residues,
                excluded_residues,
                scaffold_paths=scaffold_paths,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )

    check = subprocess.run(
        ["boltzgen", "check", str(spec_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        cwd=out_dir,
    )
    if check.returncode != 0:
        return _error(
            "Error: BoltzGen rejected the generated GPCR/nanobody design specification",
            "invalid_design_spec",
            stderr_tail=(check.stderr or "")[-2000:],
        )

    argv = [
        "boltzgen",
        "run",
        str(spec_path),
        "--output",
        str(run_dir),
        "--protocol",
        "nanobody-anything",
        "--num_designs",
        str(num_designs),
        "--budget",
        str(budget),
        "--devices",
        "1",
        "--cache",
        "/cache/boltzgen",
    ]
    if reuse:
        argv.append("--reuse")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=14000,
            cwd=out_dir,
        )
    except subprocess.TimeoutExpired as exc:
        return _error(
            "Error: BoltzGen small-set round timed out; rerun with reuse=true",
            "timeout",
            stdout_tail=(exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else "",
        )
    elapsed = round(time.monotonic() - started, 3)
    if proc.returncode != 0:
        return {
            "summary": f"Error: BoltzGen exited {proc.returncode}",
            "error": "boltzgen_failed",
            "details": {"stderr_tail": (proc.stderr or "")[-3000:]},
            "metrics": {"elapsed_s": elapsed},
        }

    final_root = run_dir / "final_ranked_designs"
    final_design_dirs = sorted(final_root.glob("final_*_designs"))
    structures = sorted(
        str(path)
        for final_dir in final_design_dirs
        for pattern in ("*.cif", "*.pdb")
        for path in final_dir.glob(pattern)
        if path.is_file()
    )
    metric_tables = sorted(str(path) for path in final_root.glob("*metrics*.csv") if path.is_file())
    design_masks: dict[str, str] = {}
    for structure in structures:
        match = re.search(r"(design_spec_\d+)", Path(structure).stem)
        if not match:
            continue
        mask = run_dir / "intermediate_designs" / f"{match.group(1)}.npz"
        if mask.exists():
            design_masks[structure] = str(mask)
    result_manifest = {
        "schema_version": 1,
        "engine": "boltzgen",
        "engine_version": "0.3.2",
        "design_mode": design_mode,
        "protocol": "nanobody-anything",
        "scaffold_reference_id": scaffold_reference_id,
        "scaffold_spec_path": str(staged_scaffold_spec) if staged_scaffold_spec else None,
        "scaffold_structure_path": (
            str(staged_scaffold_structure) if staged_scaffold_structure else None
        ),
        "scaffold_spec_sha256": _sha256(staged_scaffold_spec) if staged_scaffold_spec else None,
        "scaffold_structure_sha256": (
            _sha256(staged_scaffold_structure) if staged_scaffold_structure else None
        ),
        "binding_side": manifest.get("binding_side"),
        "receptor_state": manifest.get("receptor_state"),
        "target_label_chain": chain,
        "binding_residues_label": residues,
        "excluded_residues_label": excluded_residues,
        "num_designs_requested": num_designs,
        "budget": budget,
        "candidate_structure_paths": structures,
        "candidate_design_mask_paths": design_masks,
        "metric_table_paths": metric_tables,
        "design_spec_path": str(spec_path),
    }
    result_manifest_path = out_dir / "proteinclaw_result_manifest.json"
    result_manifest_path.write_text(json.dumps(result_manifest, indent=2), encoding="utf-8")
    return {
        "summary": (
            f"BoltzGen {design_mode} small-set round completed: requested {num_designs}, retained "
            f"{len(structures)} structure artifact(s) for a budget of {budget}"
        ),
        "output_dir": str(out_dir),
        "result_manifest_path": str(result_manifest_path),
        **result_manifest,
        "metrics": {"elapsed_s": elapsed, "num_structure_artifacts": len(structures)},
    }
