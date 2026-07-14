"""Transfer a solved GPCR-VHH pose and relax evidence-backed mutations."""

from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from Bio.Align import PairwiseAligner
from Bio.PDB import MMCIFParser, PDBIO, PDBParser, Superimposer
from Bio.PDB.Chain import Chain
from Bio.PDB.Model import Model
from Bio.PDB.Structure import Structure

_AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def _error(summary: str, error: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"summary": summary, "error": error, "metrics": {}}
    if details:
        result["details"] = details
    return result


def _workspace_file(raw: str, *, root: Path, suffixes: set[str]) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in suffixes or not path.is_file():
        raise ValueError(f"missing or unsupported workspace file: {path}")
    return path


def _resolve_manifest_file(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    recorded = Path(str(manifest.get("prepared_pdb_path") or "prepared_gpcr.pdb"))
    for candidate in (
        recorded,
        manifest_path.parent / recorded.name,
        manifest_path.parent / "prepared_gpcr.pdb",
    ):
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError("target manifest does not resolve prepared_pdb_path")


def _parse_structure(path: Path, name: str):
    parser = MMCIFParser(QUIET=True) if path.suffix.lower() in {".cif", ".mmcif"} else PDBParser(QUIET=True)
    return parser.get_structure(name, str(path))


def _residues_by_author(chain) -> dict[int, Any]:
    residues: dict[int, Any] = {}
    for residue in chain:
        if residue.id[0] != " " or residue.resname not in _AA3 or "CA" not in residue:
            continue
        author = int(residue.id[1])
        if author in residues:
            raise ValueError(f"duplicate/insertion-coded author residue {author}")
        residues[author] = residue
    return residues


def _sequence_correspondence(reference_chain, target_chain) -> tuple[list[tuple[Any, Any]], float]:
    reference = [
        residue
        for residue in reference_chain
        if residue.id[0] == " " and residue.resname in _AA3 and "CA" in residue
    ]
    target = [
        residue
        for residue in target_chain
        if residue.id[0] == " " and residue.resname in _AA3 and "CA" in residue
    ]
    reference_sequence = "".join(_AA3[residue.resname] for residue in reference)
    target_sequence = "".join(_AA3[residue.resname] for residue in target)
    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score = 2.0
    aligner.mismatch_score = -1.0
    aligner.open_gap_score = -10.0
    aligner.extend_gap_score = -0.5
    alignment = aligner.align(reference_sequence, target_sequence)[0]
    pairs: list[tuple[Any, Any]] = []
    identical = 0
    for (reference_start, reference_end), (target_start, target_end) in zip(
        alignment.aligned[0], alignment.aligned[1], strict=True
    ):
        if reference_end - reference_start != target_end - target_start:
            raise ValueError("sequence alignment returned unequal ungapped segments")
        for offset in range(reference_end - reference_start):
            reference_residue = reference[reference_start + offset]
            target_residue = target[target_start + offset]
            pairs.append((reference_residue, target_residue))
            identical += reference_residue.resname == target_residue.resname
    if not pairs:
        raise ValueError("reference and target receptor sequences do not align")
    return pairs, identical / len(pairs)


def _in_spans(value: int, spans: list[list[int]]) -> bool:
    return any(int(start) <= value <= int(end) for start, end in spans)


def _protein_chain_copy(source, chain_id: str) -> Chain:
    chain = Chain(chain_id)
    for residue in source:
        if residue.id[0] == " " and residue.resname in _AA3:
            chain.add(deepcopy(residue))
    if not any(True for _ in chain.get_residues()):
        raise ValueError(f"source chain {source.id!r} has no standard protein residues")
    return chain


def _build_pose_transfer(
    *,
    target_path: Path,
    target_chain_id: str,
    reference_path: Path,
    reference_target_chain: str,
    reference_binder_chain: str,
    membrane_spans: list[list[int]],
    max_alignment_rmsd: float,
    output_path: Path,
) -> dict[str, Any]:
    target_model = _parse_structure(target_path, "target")[0]
    reference_model = _parse_structure(reference_path, "reference")[0]
    for model, chain_id, label in (
        (target_model, target_chain_id, "prepared target"),
        (reference_model, reference_target_chain, "reference target"),
        (reference_model, reference_binder_chain, "reference binder"),
    ):
        if chain_id not in model:
            raise ValueError(f"{label} chain {chain_id!r} is absent")

    _residues_by_author(target_model[target_chain_id])
    _residues_by_author(reference_model[reference_target_chain])
    correspondence, sequence_identity = _sequence_correspondence(
        reference_model[reference_target_chain], target_model[target_chain_id]
    )
    transmembrane_pairs = [
        (reference_residue, target_residue)
        for reference_residue, target_residue in correspondence
        if _in_spans(int(target_residue.id[1]), membrane_spans)
    ]
    if len(transmembrane_pairs) < 40:
        raise ValueError(
            f"only {len(transmembrane_pairs)} sequence-aligned transmembrane CA atoms; at least 40 required"
        )
    if sequence_identity < 0.7:
        raise ValueError(f"reference/target receptor sequence identity {sequence_identity:.1%} is too low")

    superimposer = Superimposer()
    superimposer.set_atoms(
        [target_residue["CA"] for _, target_residue in transmembrane_pairs],
        [reference_residue["CA"] for reference_residue, _ in transmembrane_pairs],
    )
    if superimposer.rms is None or not math.isfinite(float(superimposer.rms)):
        raise ValueError("receptor alignment did not produce a finite RMSD")
    if float(superimposer.rms) > max_alignment_rmsd:
        raise ValueError(
            f"transmembrane alignment RMSD {float(superimposer.rms):.3f} A exceeds "
            f"the {max_alignment_rmsd:.3f} A ceiling"
        )

    target_chain = _protein_chain_copy(target_model[target_chain_id], "A")
    binder_chain = _protein_chain_copy(reference_model[reference_binder_chain], "B")
    superimposer.apply(list(binder_chain.get_atoms()))

    structure = Structure("pose_transfer")
    model = Model(0)
    structure.add(model)
    model.add(target_chain)
    model.add(binder_chain)
    io = PDBIO()
    io.set_structure(structure)
    io.save(str(output_path))
    return {
        "alignment_rmsd_angstrom": round(float(superimposer.rms), 4),
        "alignment_ca_atoms": len(transmembrane_pairs),
        "receptor_sequence_identity": round(sequence_identity, 4),
        "alignment_target_author_residues": [
            int(target_residue.id[1]) for _, target_residue in transmembrane_pairs
        ],
        "alignment_reference_author_residues": [
            int(reference_residue.id[1]) for reference_residue, _ in transmembrane_pairs
        ],
    }


def _sequence_from_topology(topology, chain_id: str) -> str:
    chain = next((value for value in topology.chains() if value.id == chain_id), None)
    if chain is None:
        raise ValueError(f"refined topology lacks chain {chain_id!r}")
    sequence: list[str] = []
    for residue in chain.residues():
        if residue.name in _AA3:
            sequence.append(_AA3[residue.name])
    return "".join(sequence)


def _mutate_and_minimize(
    *,
    input_path: Path,
    output_path: Path,
    mutations: list[str],
    expected_binder_sequence: str,
    restraint_k: float,
    max_iterations: int,
) -> dict[str, Any]:
    from openmm import CustomExternalForce, LangevinMiddleIntegrator, Platform, unit
    from openmm.app import ForceField, HBonds, Modeller, NoCutoff, PDBFile, Simulation
    from pdbfixer import PDBFixer

    fixer = PDBFixer(filename=str(input_path))
    if mutations:
        fixer.applyMutations(mutations, "B")
    fixer.findMissingResidues()
    fixer.missingResidues = {}
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(7.4)

    observed = _sequence_from_topology(fixer.topology, "B")
    if observed != expected_binder_sequence:
        raise ValueError(
            f"mutated binder sequence mismatch: observed {observed}, expected {expected_binder_sequence}"
        )

    forcefield = ForceField("amber14-all.xml", "implicit/gbn2.xml")
    system = forcefield.createSystem(
        fixer.topology,
        nonbondedMethod=NoCutoff,
        constraints=HBonds,
    )
    restraint = CustomExternalForce("0.5*k*((x-x0)^2+(y-y0)^2+(z-z0)^2)")
    restraint.addGlobalParameter("k", restraint_k * unit.kilojoule_per_mole / unit.nanometer**2)
    for parameter in ("x0", "y0", "z0"):
        restraint.addPerParticleParameter(parameter)
    for atom, position in zip(fixer.topology.atoms(), fixer.positions, strict=True):
        if atom.name in {"N", "CA", "C", "O"}:
            restraint.addParticle(atom.index, position.value_in_unit(unit.nanometer))
    system.addForce(restraint)

    integrator = LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond, 0.002 * unit.picoseconds)
    platform = Platform.getPlatformByName("CUDA")
    properties = {"Precision": "mixed"}
    simulation = Simulation(fixer.topology, system, integrator, platform, properties)
    simulation.context.setPositions(fixer.positions)
    initial = simulation.context.getState(getEnergy=True).getPotentialEnergy()
    simulation.minimizeEnergy(
        tolerance=10 * unit.kilojoule_per_mole / unit.nanometer,
        maxIterations=max_iterations,
    )
    state = simulation.context.getState(getEnergy=True, getPositions=True)
    final = state.getPotentialEnergy()

    modeller = Modeller(fixer.topology, state.getPositions())
    modeller.delete([atom for atom in modeller.topology.atoms() if atom.element.symbol == "H"])
    with output_path.open("w", encoding="utf-8") as handle:
        PDBFile.writeFile(modeller.topology, modeller.positions, handle, keepIds=True)
    return {
        "platform": platform.getName(),
        "initial_energy_kj_mol": round(initial.value_in_unit(unit.kilojoule_per_mole), 3),
        "final_energy_kj_mol": round(final.value_in_unit(unit.kilojoule_per_mole), 3),
        "restraint_k_kj_mol_nm2": restraint_k,
        "max_iterations": max_iterations,
        "binder_sequence": observed,
    }


def run(
    *,
    target_manifest_path: str,
    reference_complex_path: str,
    reference_target_chain: str,
    reference_binder_chain: str,
    binder_mutations: list[str],
    expected_binder_sequence: str,
    max_alignment_rmsd: float = 3.0,
    restraint_k: float = 1000.0,
    max_iterations: int = 1000,
    step: int = 0,
    _workspace_root: str = "/workspace",
    **_: Any,
) -> dict[str, Any]:
    started = time.monotonic()
    root = Path(_workspace_root).resolve()
    try:
        manifest_path = _workspace_file(target_manifest_path, root=root, suffixes={".json"})
        reference_path = _workspace_file(
            reference_complex_path, root=root, suffixes={".pdb", ".cif", ".mmcif"}
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if int(manifest.get("schema_version", 0)) < 3:
            raise ValueError("schema-v3 target manifest is required")
        if manifest.get("mapping_verified") is not True or manifest.get("topology_verified") is not True:
            raise ValueError("target numbering and topology must be verified")
        target_path = _resolve_manifest_file(manifest_path, manifest)
        target_chain = str(manifest["target_auth_chain"])
        spans = manifest["membrane_spans_author"]
        if not expected_binder_sequence or any(value not in _AA3.values() for value in expected_binder_sequence):
            raise ValueError("expected_binder_sequence must contain canonical amino acids")
        if not 0.5 <= max_alignment_rmsd <= 5.0:
            raise ValueError("max_alignment_rmsd must be 0.5-5.0 A")
        if not 10 <= restraint_k <= 10000 or not 1 <= max_iterations <= 10000:
            raise ValueError("restraint_k or max_iterations is outside the supported range")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _error(f"Error: invalid pose-refinement input: {exc}", "invalid_args")

    out_dir = root / f"gpcr_pose_refine_{step}"
    out_dir.mkdir(parents=True, exist_ok=True)
    transferred = out_dir / "transferred_pose.pdb"
    refined = out_dir / "refined_complex.pdb"
    try:
        alignment = _build_pose_transfer(
            target_path=target_path,
            target_chain_id=target_chain,
            reference_path=reference_path,
            reference_target_chain=reference_target_chain,
            reference_binder_chain=reference_binder_chain,
            membrane_spans=spans,
            max_alignment_rmsd=max_alignment_rmsd,
            output_path=transferred,
        )
        relaxation = _mutate_and_minimize(
            input_path=transferred,
            output_path=refined,
            mutations=binder_mutations,
            expected_binder_sequence=expected_binder_sequence,
            restraint_k=restraint_k,
            max_iterations=max_iterations,
        )
    except Exception as exc:  # noqa: BLE001 - return a structured scientific/tool failure
        return _error(
            f"Error: pose transfer or restrained minimization failed: {exc}",
            "pose_refinement_failed",
            exception_type=type(exc).__name__,
        )

    return {
        "summary": (
            f"Transferred solved VHH pose onto {manifest.get('receptor_state')} GPCR "
            f"(TM RMSD {alignment['alignment_rmsd_angstrom']:.3f} A) and minimized "
            f"{len(binder_mutations)} mutation(s)"
        ),
        "engine": "OpenMM",
        "engine_version": "8.5.2",
        "target_state": manifest.get("receptor_state"),
        "target_source_id": manifest.get("source_id"),
        "reference_complex_path": str(reference_path),
        "transferred_pose_path": str(transferred),
        "refined_complex_path": str(refined),
        "binder_mutations": binder_mutations,
        "alignment": alignment,
        "relaxation": relaxation,
        "metrics": {
            "elapsed_s": round(time.monotonic() - started, 3),
            "alignment_rmsd_angstrom": alignment["alignment_rmsd_angstrom"],
            "final_energy_kj_mol": relaxation["final_energy_kj_mol"],
        },
        "notes": [
            "The VHH pose is homolog-transferred from an experimental complex and is not a de novo pose prediction.",
            "Backbone restraints preserve the experimental pose while mutated side chains relax in implicit solvent.",
            "This modeled complex is computational prioritization, not experimental validation.",
        ],
    }


__all__ = ["_build_pose_transfer", "run"]
