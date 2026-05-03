"""Tool handlers for the protein-design plugin."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from .clients import (
    inspect_structure_file,
    parse_mmcif_residues,
    parse_pdb_residues,
    search_pubmed,
    search_rcsb,
    search_uniprot,
)
from .runtime import (
    DEFAULT_ESMFOLD_IMAGE,
    DEFAULT_FOUNDRY_IMAGE,
    check_docker_requirements,
    common_mount_root,
    config_value,
    ensure_workspace,
    json_result,
    resolve_workspace_path,
    run_docker,
    to_container_path,
)


VALID_RFD3_MODES = {"free_generation", "binder", "motif_scaffold", "partial_diffusion"}
CHAIN_RANGE_RE = re.compile(r"^([A-Za-z0-9_])(-?\d+)(?:-(-?\d+))?$")
DESIGN_RANGE_RE = re.compile(r"^\d+(?:-\d+)?$")
AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYXBZUOJ:\-\s]+$", re.IGNORECASE)


def _clamp_int(value: Any, default: int, low: int, high: int | None = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    parsed = max(low, parsed)
    if high is not None:
        parsed = min(high, parsed)
    return parsed


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _chain_segments(contig: str) -> list[str]:
    segments: list[str] = []
    for raw in contig.split(","):
        item = raw.strip()
        if not item or item == "/0":
            continue
        if DESIGN_RANGE_RE.match(item):
            continue
        segments.append(item)
    return segments


def _load_structure_residues(path: Path) -> dict[str, set[int]]:
    # Tool-side validation is deliberately lightweight. PDB is parsed fully
    # enough to catch common bad chain/range mistakes; CIF files are accepted
    # and left to RFD3 prevalidation because robust CIF parsing is a dependency
    # we do not want in the ProteinClaw process.
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".pdb") or suffixes.endswith(".ent"):
        return parse_pdb_residues(path)
    if suffixes.endswith(".pdb.gz") or suffixes.endswith(".ent.gz"):
        temp = path.with_suffix("")
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as src:
            content = src.read()
        temp.write_text(content, encoding="utf-8")
        try:
            return parse_pdb_residues(temp)
        finally:
            temp.unlink(missing_ok=True)
    if suffixes.endswith(".cif") or suffixes.endswith(".mmcif"):
        return parse_mmcif_residues(path)
    if suffixes.endswith(".cif.gz") or suffixes.endswith(".mmcif.gz"):
        temp = path.with_suffix("")
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as src:
            content = src.read()
        temp.write_text(content, encoding="utf-8")
        try:
            return parse_mmcif_residues(temp)
        finally:
            temp.unlink(missing_ok=True)
    return {}


def validate_rfd3_contig(
    *,
    mode: str,
    contig: str,
    target_pdb_path: str = "",
    hotspot_residues: list[str] | None = None,
    input_path: str = "",
) -> list[str]:
    errors: list[str] = []
    if mode not in VALID_RFD3_MODES:
        errors.append(f"Invalid mode: {mode}")
    if not contig or not isinstance(contig, str):
        errors.append("contig is required")
        return errors

    for segment in _chain_segments(contig):
        if not CHAIN_RANGE_RE.match(segment):
            errors.append(f"Invalid fixed residue segment in contig: {segment}")

    if mode != "free_generation" and not target_pdb_path and not input_path:
        errors.append("target_pdb_path is required for target-conditioned RFD3 modes")
        return errors

    if mode != "free_generation" and input_path and not target_pdb_path:
        # Existing RFD3 JSON/YAML specs may already contain the target path and
        # richer constraints. The tool still forwards prevalidate_inputs=True so
        # Foundry performs authoritative validation inside the target runtime.
        return errors

    if mode == "free_generation":
        if any(CHAIN_RANGE_RE.match(seg) for seg in _chain_segments(contig)):
            errors.append("free_generation contig should use designed bare lengths only")
        return errors

    try:
        target = resolve_workspace_path(target_pdb_path, must_exist=True)
    except Exception as exc:
        errors.append(str(exc))
        return errors

    residues = _load_structure_residues(target)
    if not residues:
        return errors

    def _check_residue_expr(expr: str, source: str) -> None:
        match = CHAIN_RANGE_RE.match(expr)
        if not match:
            errors.append(f"Invalid {source} residue expression: {expr}")
            return
        chain, start_s, end_s = match.groups()
        start = int(start_s)
        end = int(end_s or start_s)
        chain_residues = residues.get(chain)
        if not chain_residues:
            errors.append(f"{source} references missing chain {chain}: {expr}")
            return
        missing = [resi for resi in range(min(start, end), max(start, end) + 1) if resi not in chain_residues]
        if missing:
            preview = ",".join(str(x) for x in missing[:5])
            errors.append(f"{source} references missing residues in {expr}: {preview}")

    for segment in _chain_segments(contig):
        _check_residue_expr(segment, "contig")
    for hotspot in hotspot_residues or []:
        _check_residue_expr(hotspot, "hotspot_residues")
    return errors


def build_rfd3_spec(args: dict[str, Any], target_container_path: str | None) -> dict[str, Any]:
    mode = str(args.get("mode", "")).strip()
    contig = str(args.get("contig", "")).strip()
    hotspots = _as_list(args.get("hotspot_residues"))

    spec: dict[str, Any]
    if mode == "free_generation":
        spec = {"length": contig}
    else:
        spec = {
            "input": target_container_path,
            "contig": contig,
        }
        if hotspots:
            spec["select_hotspots"] = ",".join(hotspots)
    if mode == "partial_diffusion":
        # A conservative default that enables partial diffusion while keeping
        # the user's simplified API small. Advanced tuning can use input_path.
        spec.setdefault("partial_t", 5.0)
    return {str(args.get("output_name", "design")): spec}


def build_rfd3_docker_args(
    *,
    input_path: str,
    out_dir: str,
    output_name: str,
    num_designs: int,
    guide_scale: float,
    num_timesteps: int,
) -> list[str]:
    return [
        "rfd3",
        "design",
        f"out_dir={out_dir}",
        f"inputs={input_path}",
        f"diffusion_batch_size={num_designs}",
        f"inference_sampler.step_scale={guide_scale}",
        f"inference_sampler.num_timesteps={num_timesteps}",
        "prevalidate_inputs=True",
        "skip_existing=False",
        f"global_prefix={output_name}",
    ]


def handle_pubmed_search(args: dict[str, Any], **_: Any) -> str:
    try:
        result = search_pubmed(
            str(args.get("query", "")),
            max_results=_clamp_int(args.get("max_results"), 20, 1, 100),
            date_range=str(args.get("date_range") or ""),
            article_types=_as_list(args.get("article_types")),
            query_variations=bool(args.get("query_variations", True)),
        )
        return json_result(success=True, **result)
    except Exception as exc:
        return json_result(success=False, error=str(exc))


def handle_uniprot_search(args: dict[str, Any], **_: Any) -> str:
    try:
        result = search_uniprot(
            str(args.get("query", "")),
            organism_id=str(args.get("organism_id") or ""),
            gene=str(args.get("gene") or ""),
            reviewed_only=bool(args.get("reviewed_only", True)),
            max_results=_clamp_int(args.get("max_results"), 25, 1, 100),
            include_sequence=bool(args.get("include_sequence", True)),
        )
        return json_result(success=True, **result)
    except Exception as exc:
        return json_result(success=False, error=str(exc))


def handle_rcsb_search(args: dict[str, Any], **_: Any) -> str:
    try:
        result = search_rcsb(
            str(args.get("query", "")),
            search_type=str(args.get("search_type") or "text"),
            max_results=_clamp_int(args.get("max_results"), 25, 1, 100),
            return_type=str(args.get("return_type") or "entry"),
            download=bool(args.get("download", False)),
            output_dir=str(args.get("output_dir") or ""),
            download_format=str(args.get("download_format") or "cif"),
            pdb_ids=_as_list(args.get("pdb_ids")),
        )
        return json_result(success=True, **result)
    except Exception as exc:
        return json_result(success=False, error=str(exc))


def handle_inspect_structure(args: dict[str, Any], **_: Any) -> str:
    try:
        structure = resolve_workspace_path(str(args.get("structure_path") or ""), must_exist=True)
        suffixes = "".join(structure.suffixes).lower()
        if suffixes.endswith((".pdb.gz", ".ent.gz", ".cif.gz", ".mmcif.gz")):
            temp_suffix = "".join(structure.suffixes[:-1])
            temp = structure.with_name(f"{structure.stem}_inspect{temp_suffix}")
            with gzip.open(structure, "rt", encoding="utf-8", errors="replace") as src:
                temp.write_text(src.read(), encoding="utf-8")
            try:
                result = inspect_structure_file(temp)
            finally:
                temp.unlink(missing_ok=True)
            result["path"] = str(structure)
            result["compressed"] = True
        else:
            result = inspect_structure_file(structure)
            result["compressed"] = False
        return json_result(success=True, **result)
    except Exception as exc:
        return json_result(success=False, error=str(exc))


def handle_rfd3_design(args: dict[str, Any], **_: Any) -> str:
    mode = str(args.get("mode", "")).strip()
    output_name = str(args.get("output_name") or "rfd3_design").strip()
    contig = str(args.get("contig", "")).strip()
    hotspots = _as_list(args.get("hotspot_residues"))
    target_arg = str(args.get("target_pdb_path") or "")
    errors = validate_rfd3_contig(
        mode=mode,
        contig=contig,
        target_pdb_path=target_arg,
        hotspot_residues=hotspots,
        input_path=str(args.get("input_path") or ""),
    )
    if errors:
        return json_result(success=False, error="RFD3 input validation failed", details=errors)

    try:
        paths: list[Path] = []
        input_path_arg = str(args.get("input_path") or "")
        target_path = resolve_workspace_path(target_arg, must_exist=True) if target_arg else None
        if target_path:
            paths.append(target_path)
        input_path = resolve_workspace_path(input_path_arg, must_exist=True) if input_path_arg else None
        if input_path:
            paths.append(input_path)
        mount_root = common_mount_root(paths)
        out_dir = ensure_workspace(mount_root / output_name)

        if input_path:
            input_container = to_container_path(input_path, mount_root)
        else:
            target_container = to_container_path(target_path, mount_root) if target_path else None
            spec = build_rfd3_spec(args, target_container)
            spec_path = mount_root / f"{output_name}_rfd3_input.json"
            spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
            input_container = to_container_path(spec_path, mount_root)

        docker_args = build_rfd3_docker_args(
            input_path=input_container,
            out_dir=to_container_path(out_dir, mount_root),
            output_name=output_name,
            num_designs=_clamp_int(args.get("num_designs"), 8, 1, 512),
            guide_scale=float(args.get("guide_scale", 1.5) or 1.5),
            num_timesteps=_clamp_int(args.get("num_timesteps"), 200, 1, None),
        )
        run = run_docker(
            str(config_value("foundry_image", DEFAULT_FOUNDRY_IMAGE)),
            docker_args,
            mount_root=mount_root,
        )
        output_files = [str(p) for p in out_dir.rglob("*") if p.is_file()] if out_dir.exists() else []
        return json_result(success=run["success"], output_dir=str(out_dir), output_files=output_files, docker=run)
    except Exception as exc:
        return json_result(success=False, error=str(exc))


def build_mpnn_docker_args(args: dict[str, Any], structure_container_path: str) -> list[str]:
    output_name = str(args.get("output_name") or "mpnn_design")
    model_type = str(args.get("model_type") or "protein_mpnn")
    foundry_model_type = "protein_mpnn" if model_type == "soluble_mpnn" else model_type
    checkpoint_path = {
        "protein_mpnn": "/weights/proteinmpnn_v_48_020.pt",
        "soluble_mpnn": "/weights/proteinmpnn_v_48_020.pt",
        "ligand_mpnn": "/weights/ligandmpnn_v_32_010_25.pt",
    }.get(model_type)
    command = [
        "mpnn",
        "--structure_path", structure_container_path,
        "--model_type", foundry_model_type,
        "--out_directory", f"/work/{output_name}",
        "--number_of_batches", str(_clamp_int(args.get("num_sequences"), 16, 1, None)),
        "--temperature", str(float(args.get("temperature", 0.1) or 0.1)),
    ]
    if checkpoint_path:
        command.extend(["--checkpoint_path", checkpoint_path])
    if model_type in {"protein_mpnn", "ligand_mpnn", "soluble_mpnn"}:
        command.extend(["--is_legacy_weights", "True"])
    if args.get("fixed_positions"):
        command.extend(["--fixed_positions", str(args["fixed_positions"])])
    if args.get("designed_chains"):
        command.extend(["--designed_chains", str(args["designed_chains"])])
    return command


def _mpnn_structure_inputs(args: dict[str, Any]) -> list[Path]:
    explicit_paths = _as_list(args.get("structure_paths"))
    if explicit_paths:
        return [resolve_workspace_path(path, must_exist=True) for path in explicit_paths]

    structure_arg = str(args.get("structure_path") or "").strip()
    if not structure_arg:
        raise ValueError("structure_path or structure_paths is required")
    structure = resolve_workspace_path(structure_arg, must_exist=True)
    if not structure.is_dir():
        return [structure]

    patterns = ("*.pdb", "*.ent", "*.cif", "*.mmcif", "*.pdb.gz", "*.ent.gz", "*.cif.gz", "*.mmcif.gz")
    structures: list[Path] = []
    for pattern in patterns:
        structures.extend(sorted(structure.glob(pattern)))
    if not structures:
        raise ValueError(f"No PDB/CIF structure files found in directory: {structure}")
    return structures


def _safe_output_suffix(path: Path) -> str:
    name = path.name
    for suffix in (".pdb.gz", ".ent.gz", ".cif.gz", ".mmcif.gz", ".pdb", ".ent", ".cif", ".mmcif"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "structure"


def handle_protein_mpnn_design(args: dict[str, Any], **_: Any) -> str:
    try:
        structures = _mpnn_structure_inputs(args)
        mount_root = common_mount_root(structures)
        output_name = str(args.get("output_name") or "mpnn_design")
        runs: list[dict[str, Any]] = []
        output_dirs: list[str] = []
        output_files: list[str] = []

        for index, structure in enumerate(structures, start=1):
            run_args = dict(args)
            if len(structures) > 1:
                run_args["output_name"] = f"{output_name}_{index}_{_safe_output_suffix(structure)}"
            docker_args = build_mpnn_docker_args(run_args, to_container_path(structure, mount_root))
            run = run_docker(str(config_value("foundry_image", DEFAULT_FOUNDRY_IMAGE)), docker_args, mount_root=mount_root)
            out_dir = mount_root / str(run_args.get("output_name") or "mpnn_design")
            output_dirs.append(str(out_dir))
            if out_dir.exists():
                output_files.extend(str(p) for p in out_dir.rglob("*") if p.is_file())
            runs.append({"structure_path": str(structure), "output_dir": str(out_dir), "docker": run})

        return json_result(
            success=all(item["docker"]["success"] for item in runs),
            output_dir=output_dirs[0] if len(output_dirs) == 1 else None,
            output_dirs=output_dirs,
            output_files=output_files,
            runs=runs,
        )
    except Exception as exc:
        return json_result(success=False, error=str(exc))


def _write_fasta(sequence: str, output_name: str, root: Path) -> Path:
    cleaned = re.sub(r"\s+", "", sequence).upper()
    if not cleaned or not AA_RE.match(cleaned):
        raise ValueError("sequence contains unsupported amino-acid characters")
    path = root / f"{output_name}.fasta"
    path.write_text(f">{output_name}\n{cleaned}\n", encoding="utf-8")
    return path


def _write_multimer_fasta(args: dict[str, Any], output_name: str, root: Path) -> Path:
    sequence = str(args.get("sequence") or "").strip()
    if not sequence:
        binder = str(args.get("binder_sequence") or "").strip()
        target = str(args.get("target_sequence") or "").strip()
        if binder and target:
            sequence = f"{binder}:{target}"
        else:
            sequences = _as_list(args.get("sequences"))
            if sequences:
                sequence = ":".join(sequences)
    if not sequence:
        raise ValueError("Provide fasta_path, sequence, binder_sequence + target_sequence, or sequences.")
    return _write_fasta(sequence, output_name, root)


def build_alphafold2_multimer_docker_args(
    args: dict[str, Any],
    fasta_container_path: str,
    output_container_dir: str,
) -> list[str]:
    command = str(args.get("command") or config_value("alphafold2_command", "colabfold_batch"))
    model_type = str(args.get("model_type") or "alphafold2_multimer_v3")
    return [
        command,
        "--model-type", model_type,
        "--num-recycle", str(_clamp_int(args.get("num_recycles"), 3, 1, None)),
        fasta_container_path,
        output_container_dir,
    ]


def handle_alphafold2_multimer_predict(args: dict[str, Any], **_: Any) -> str:
    try:
        output_name = str(args.get("output_name") or "af2_multimer").strip()
        root = ensure_workspace()
        fasta_arg = str(args.get("fasta_path") or "").strip()
        if fasta_arg:
            fasta_path = resolve_workspace_path(fasta_arg, must_exist=True)
            mount_root = common_mount_root([fasta_path], fallback=root)
        else:
            mount_root = root
            fasta_path = _write_multimer_fasta(args, output_name, mount_root)
        out_dir = ensure_workspace(mount_root / output_name)
        docker_args = build_alphafold2_multimer_docker_args(
            args,
            to_container_path(fasta_path, mount_root),
            to_container_path(out_dir, mount_root),
        )
        image = str(args.get("image") or config_value("alphafold2_image", "ghcr.io/sokrypton/colabfold:1.6.1-cuda12"))
        run = run_docker(
            image,
            docker_args,
            mount_root=mount_root,
            gpus=not bool(args.get("cpu_only")),
            timeout=_clamp_int(args.get("timeout_seconds"), int(config_value("default_timeout_seconds", 7200)), 60, None),
        )
        output_files = [str(p) for p in out_dir.rglob("*") if p.is_file()] if out_dir.exists() else []
        structure_files = [
            path for path in output_files
            if path.lower().endswith((".pdb", ".cif", ".mmcif", ".pdb.gz", ".cif.gz", ".mmcif.gz"))
        ]
        json_files = [path for path in output_files if path.lower().endswith(".json")]
        return json_result(
            success=run["success"],
            output_dir=str(out_dir),
            structure_files=structure_files,
            json_files=json_files,
            output_files=output_files,
            docker=run,
        )
    except Exception as exc:
        return json_result(success=False, error=str(exc))


def build_esmfold_input_payload(
    args: dict[str, Any],
    *,
    sequence: str | None,
    fasta_container_path: str | None,
    output_container_dir: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sequence": sequence,
        "fasta_path": fasta_container_path,
        "output_dir": output_container_dir,
        "sequence_name": str(args.get("output_name") or "sequence"),
        "num_recycles": _clamp_int(args.get("num_recycles"), 4, 1, None),
        "max_tokens_per_batch": _clamp_int(args.get("max_tokens_per_batch"), 1024, 1, None),
        "cpu_only": bool(args.get("cpu_only")),
        "cpu_offload": bool(args.get("cpu_offload")),
    }
    if args.get("chunk_size") is not None:
        payload["chunk_size"] = _clamp_int(args.get("chunk_size"), 128, 1, None)
    return payload


def build_esmfold_docker_args(
    _args: dict[str, Any],
    _input_container_path: str,
    _output_container_path: str,
) -> list[str]:
    # The image entrypoint reads JSON from INPUT_FILE and writes OUTPUT_FILE.
    # Keep this function for tests and future CLI compatibility.
    return []


def handle_esmfold_predict(args: dict[str, Any], **_: Any) -> str:
    try:
        output_name = str(args.get("output_name") or "esmfold").strip()
        root = ensure_workspace()
        fasta_arg = str(args.get("fasta_path") or "")
        sequence: str | None = None
        if fasta_arg:
            fasta_path = resolve_workspace_path(fasta_arg, must_exist=True)
            mount_root = common_mount_root([fasta_path], fallback=root)
        else:
            sequence = str(args.get("sequence") or "").strip()
            if not sequence:
                return json_result(
                    success=False,
                    error="Either sequence or fasta_path is required for esmfold_predict",
                    guidance="Run ESMFold only after you have a designed/natural amino-acid sequence or a FASTA file.",
                )
            mount_root = root
            fasta_path = _write_fasta(sequence, output_name, mount_root)
        out_dir = ensure_workspace(mount_root / output_name)
        input_json = mount_root / f"{output_name}_esmfold_input.json"
        output_json = out_dir / "esmfold_result.json"
        payload = build_esmfold_input_payload(
            args,
            sequence=None if fasta_arg else sequence,
            fasta_container_path=to_container_path(fasta_path, mount_root) if fasta_arg else None,
            output_container_dir=to_container_path(out_dir, mount_root),
        )
        input_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        docker_args = build_esmfold_docker_args(
            args,
            to_container_path(input_json, mount_root),
            to_container_path(output_json, mount_root),
        )
        run = run_docker(
            str(config_value("esmfold_image", DEFAULT_ESMFOLD_IMAGE)),
            docker_args,
            mount_root=mount_root,
            gpus=not bool(args.get("cpu_only")),
            env={
                "INPUT_FILE": to_container_path(input_json, mount_root),
                "OUTPUT_FILE": to_container_path(output_json, mount_root),
            },
        )
        pdb_files = [str(p) for p in out_dir.rglob("*.pdb")] if out_dir.exists() else []
        result_payload: dict[str, Any] = {}
        if output_json.exists():
            try:
                result_payload = json.loads(output_json.read_text(encoding="utf-8"))
            except Exception:
                result_payload = {"result_json": str(output_json)}
        return json_result(
            success=run["success"],
            output_dir=str(out_dir),
            pdb_files=pdb_files,
            result=result_payload,
            docker=run,
        )
    except Exception as exc:
        return json_result(success=False, error=str(exc))
