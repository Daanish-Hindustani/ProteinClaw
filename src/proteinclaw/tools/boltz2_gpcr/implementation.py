"""State-conditioned Boltz-2 confirmation for GPCR/nanobody complexes."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

_AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
_SEQ_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")


def _error(summary: str, error: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"summary": summary, "error": error, "metrics": {}}
    if details:
        result["details"] = details
    return result


def _workspace_file(raw: str, *, workspace_root: Path, suffixes: set[str]) -> Path:
    root = workspace_root.expanduser().resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path must live under {root}")
    if path.suffix.lower() not in suffixes or not path.is_file():
        raise ValueError(f"missing or unsupported workspace file: {path}")
    return path


def _resolve_recorded_file(
    manifest_path: Path, manifest: dict[str, Any], field: str, fallback: str
) -> Path:
    recorded = Path(str(manifest.get(field) or fallback))
    for candidate in (recorded, manifest_path.parent / recorded.name, manifest_path.parent / fallback):
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    raise ValueError(f"target manifest does not resolve {field}")


def _parse_pdb_chain(path: Path, chain_id: str) -> tuple[str, list[int]]:
    residues: list[tuple[tuple[int, str], str]] = []
    seen: set[tuple[int, str]] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27 or line[21].strip() != chain_id:
            continue
        resname = line[17:20].strip()
        if resname not in _AA3:
            continue
        try:
            resid = int(line[22:26])
        except ValueError:
            continue
        key = (resid, line[26].strip())
        if key in seen:
            continue
        seen.add(key)
        residues.append((key, _AA3[resname]))
    if not residues:
        raise ValueError(f"no standard residues found on template chain {chain_id!r}")
    return "".join(aa for _, aa in residues), [key[0] for key, _ in residues]


def _input_payload(
    *,
    target_sequence: str,
    binder_sequence: str,
    template_path: Path,
    template_chain: str,
    anchor_indices: list[int],
    use_msa_server: bool,
    force_template: bool,
    template_threshold: float,
    force_pocket: bool,
) -> dict[str, Any]:
    target: dict[str, Any] = {"id": "A", "sequence": target_sequence}
    binder: dict[str, Any] = {"id": "B", "sequence": binder_sequence}
    if not use_msa_server:
        target["msa"] = "empty"
        binder["msa"] = "empty"
    return {
        "version": 1,
        "sequences": [{"protein": target}, {"protein": binder}],
        "constraints": [
            {
                "pocket": {
                    "binder": "B",
                    "contacts": [["A", value] for value in anchor_indices],
                    "max_distance": 8.0,
                    "force": force_pocket,
                }
            }
        ],
        "templates": [
            {
                "cif": str(template_path),
                "chain_id": "A",
                "template_id": template_chain,
                "force": force_template,
                "threshold": template_threshold,
            }
        ],
    }


def run(
    *,
    target_manifest_path: str,
    binder_sequence: str,
    use_msa_server: bool = True,
    diffusion_samples: int = 5,
    recycling_steps: int = 3,
    force_template: bool = True,
    template_threshold: float = 1.5,
    force_pocket: bool = False,
    use_potentials: bool = True,
    step: int = 0,
    _workspace_root: str = "/workspace",
    **_: Any,
) -> dict[str, Any]:
    if not _SEQ_RE.fullmatch(binder_sequence or "") or not 80 <= len(binder_sequence) <= 180:
        return _error("Error: binder_sequence must be an 80-180 aa canonical sequence", "invalid_args")
    if not 1 <= diffusion_samples <= 5 or not 1 <= recycling_steps <= 10:
        return _error("Error: diffusion_samples must be 1-5 and recycling_steps 1-10", "invalid_args")
    if not 0.5 <= template_threshold <= 5.0:
        return _error("Error: template_threshold must be 0.5-5.0 A", "invalid_args")

    try:
        workspace = Path(_workspace_root).resolve()
        manifest_path = _workspace_file(
            target_manifest_path,
            workspace_root=workspace,
            suffixes={".json"},
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if int(manifest.get("schema_version", 0)) < 3:
            raise ValueError("schema-v3 GPCR target manifest is required")
        for field in ("mapping_verified", "topology_verified", "full_chain_preserved"):
            if manifest.get(field) is not True:
                raise ValueError(f"target manifest does not certify {field}")
        if manifest.get("target_representation", {}).get("confirmation_state_preserved") is not True:
            raise ValueError("target manifest does not require state-preserving confirmation")
        sequence_pdb_path = _resolve_recorded_file(
            manifest_path, manifest, "prepared_pdb_path", "prepared_gpcr.pdb"
        )
        template_path = _resolve_recorded_file(
            manifest_path, manifest, "prepared_mmcif_path", "prepared_gpcr.cif"
        )
        author_chain = str(manifest["target_auth_chain"])
        template_chain = str(manifest["target_label_chain"])
        target_sequence, author_resids = _parse_pdb_chain(sequence_pdb_path, author_chain)
        sequence_index = {resid: index + 1 for index, resid in enumerate(author_resids)}
        anchor_author = [int(value) for value in manifest["binding_residues_author"]]
        anchor_indices = [sequence_index[value] for value in anchor_author]
        if len(anchor_indices) < 2:
            raise ValueError("at least two resolved epitope anchors are required")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _error(f"Error: invalid state-conditioned target: {exc}", "invalid_args")

    out_dir = workspace / f"boltz2_gpcr_{step}"
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / "gpcr_complex.yaml"
    payload = _input_payload(
        target_sequence=target_sequence,
        binder_sequence=binder_sequence,
        template_path=template_path,
        template_chain=template_chain,
        anchor_indices=anchor_indices,
        use_msa_server=use_msa_server,
        force_template=force_template,
        template_threshold=template_threshold,
        force_pocket=force_pocket,
    )
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    lock_path = out_dir / "input_fingerprint.json"
    lock = {"sha256": fingerprint, "engine": "boltz", "engine_version": "2.2.1"}
    if lock_path.exists() and json.loads(lock_path.read_text(encoding="utf-8")) != lock:
        return _error("Error: inputs changed for an existing step; use a new step", "stale_step")
    lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    spec_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    prediction_root = out_dir / "prediction"
    argv = [
        "boltz", "predict", str(spec_path), "--out_dir", str(prediction_root),
        "--cache", "/cache/boltz2", "--devices", "1", "--accelerator", "gpu",
        "--recycling_steps", str(recycling_steps), "--diffusion_samples", str(diffusion_samples),
        "--max_parallel_samples", str(diffusion_samples), "--output_format", "mmcif",
        "--override",
    ]
    if use_msa_server:
        argv.append("--use_msa_server")
    if use_potentials:
        argv.append("--use_potentials")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=7200, cwd=out_dir
        )
    except subprocess.TimeoutExpired as exc:
        return _error(
            "Error: state-conditioned Boltz-2 prediction timed out",
            "timeout",
            stdout_tail=(exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else "",
        )
    elapsed = round(time.monotonic() - started, 3)
    if proc.returncode != 0:
        return _error(
            f"Error: Boltz-2 exited {proc.returncode}",
            "boltz2_failed",
            stderr_tail=(proc.stderr or "")[-3000:],
            stdout_tail=(proc.stdout or "")[-1000:],
        )

    prediction_candidates = (
        prediction_root / "predictions" / "gpcr_complex",
        prediction_root
        / "boltz_results_gpcr_complex"
        / "predictions"
        / "gpcr_complex",
    )
    pred_dir = next(
        (candidate for candidate in prediction_candidates if candidate.is_dir()),
        prediction_candidates[0],
    )
    structures = sorted(pred_dir.glob("gpcr_complex_model_*.cif"))
    records: list[dict[str, Any]] = []
    for structure in structures:
        model = structure.stem.rsplit("_", 1)[-1]
        confidence_path = pred_dir / f"confidence_gpcr_complex_model_{model}.json"
        if not confidence_path.exists():
            continue
        confidence = json.loads(confidence_path.read_text(encoding="utf-8"))
        records.append(
            {
                "model": int(model),
                "structure_path": str(structure),
                "confidence_path": str(confidence_path),
                "confidence_score": confidence.get("confidence_score"),
                "iptm": confidence.get("iptm"),
                "protein_iptm": confidence.get("protein_iptm"),
                "complex_plddt": confidence.get("complex_plddt"),
                "complex_iplddt": confidence.get("complex_iplddt"),
                "complex_ipde": confidence.get("complex_ipde"),
                "pair_chains_iptm": confidence.get("pair_chains_iptm"),
            }
        )
    if len(records) != diffusion_samples:
        return _error(
            f"Error: expected {diffusion_samples} Boltz-2 confidence records, found {len(records)}",
            "missing_predictions",
            stderr_tail=(proc.stderr or "")[-3000:],
            stdout_tail=(proc.stdout or "")[-3000:],
        )
    best = max(records, key=lambda row: float(row.get("confidence_score") or -1))
    return {
        "summary": (
            f"State-conditioned Boltz-2: {len(records)} sample(s), best ipTM "
            f"{float(best.get('iptm') or 0):.3f}, interface pLDDT "
            f"{float(best.get('complex_iplddt') or 0):.3f}"
        ),
        "engine": "boltz",
        "engine_version": "2.2.1",
        "receptor_state": manifest.get("receptor_state"),
        "binding_side": manifest.get("binding_side"),
        "target_template_path": str(template_path),
        "target_template_forced": force_template,
        "template_threshold": template_threshold,
        "pocket_constraint_forced": force_pocket,
        "potentials_used": use_potentials,
        "anchor_indices": anchor_indices,
        "input_spec_path": str(spec_path),
        "prediction_dir": str(pred_dir),
        "samples": records,
        "best_sample": best,
        "metrics": {
            "elapsed_s": elapsed,
            "num_samples": len(records),
            "best_iptm": best.get("iptm"),
            "best_complex_iplddt": best.get("complex_iplddt"),
        },
        "notes": [
            "The receptor template preserves the experimentally observed state; the binder pose is not templated.",
            "Pocket conditioning is disclosed and must be identical for candidate and negative control.",
            "A high score is computational prioritization, not experimental validation.",
        ],
    }
