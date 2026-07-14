"""Fail-closed, GPCR-aware interface QC for generated nanobody complexes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from proteinclaw.analysis import InterfaceMetricsError, compute_interface_metrics
from proteinclaw.tools import registry

_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "complex_path": {
            "type": "string",
            "minLength": 1,
            "description": "Predicted nanobody-GPCR complex in PDB or mmCIF format.",
        },
        "target_manifest_path": {
            "type": "string",
            "minLength": 1,
            "description": "Verified schema-v2 manifest used to generate the candidate.",
        },
        "binder_chain": {"type": "string", "default": "B"},
        "target_chain": {"type": "string", "default": "A"},
        "target_numbering": {
            "type": "string",
            "enum": ["manifest_label", "manifest_author", "prediction_sequence"],
            "default": "manifest_label",
            "description": (
                "Use prediction_sequence for predictors such as Boltz-2 that renumber the "
                "resolved target sequence from one; the mapping is derived from the prepared GPCR."
            ),
        },
        "cdr_ranges": {
            "type": "string",
            "description": "JSON CDR ranges on the binder chain; required unless design_mask_path is supplied.",
        },
        "design_mask_path": {
            "type": "string",
            "description": "BoltzGen intermediate .npz design mask used to derive exact scaffold-specific CDR ranges.",
        },
        "min_bsa": {"type": "number", "minimum": 0, "default": 1000.0},
        "max_bsa": {"type": "number", "minimum": 0, "default": 3200.0},
        "min_hotspot_satisfaction": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 0.5,
        },
        "min_mapped_hotspot_fraction": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 0.9,
            "description": "Fraction of intended hotspots that must be present in the candidate coordinates.",
        },
        "max_clash_score": {"type": "number", "minimum": 0, "default": 5.0},
        "min_cdr_contact_fraction": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 0.6,
        },
        "min_interface_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 0.7,
            "description": "Minimum mean interface confidence, normalized to 0..1.",
        },
        "min_h3_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 0.7,
            "description": "Minimum CDR3 confidence, normalized to 0..1.",
        },
        "confidence_policy": {
            "type": "string",
            "enum": ["required", "external_confirmation"],
            "default": "required",
            "description": (
                "Use external_confirmation only for experimental-pose/force-field models "
                "that have no meaningful pLDDT; this can pass geometry but never strict QC alone."
            ),
        },
        "reference_complex_path": {
            "type": "string",
            "description": "Optional solved, same-face GPCR-VHH complex used to calibrate BSA and clashes.",
        },
        "reference_binder_chain": {"type": "string", "default": "B"},
        "reference_target_chain": {"type": "string", "default": "A"},
        "reference_cdr_ranges": {
            "type": "string",
            "description": "Optional JSON CDR ranges for reference-based CDR-contact calibration.",
        },
        "reference_bsa_min_ratio": {"type": "number", "minimum": 0, "default": 0.65},
        "reference_bsa_max_ratio": {"type": "number", "minimum": 0, "default": 1.35},
        "reference_clash_tolerance": {"type": "number", "minimum": 0, "default": 3.0},
        "reference_cdr_tolerance": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.05},
        "session_id": {"type": "string"},
    },
    "required": ["complex_path", "target_manifest_path"],
}

_CONFIRMATION_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidate_afm_score_path": {
            "type": "string",
            "minLength": 1,
            "description": "JSON result from analysis.afm_screen_score for the candidate.",
        },
        "negative_control_afm_score_path": {
            "type": "string",
            "minLength": 1,
            "description": "JSON AF-M screen score for a same-target decoy or wrong-face control.",
        },
        "candidate_qc_path": {
            "type": "string",
            "minLength": 1,
            "description": "JSON result from analysis.gpcr_candidate_qc for the candidate.",
        },
        "min_models": {"type": "integer", "minimum": 2, "maximum": 5, "default": 5},
        "min_avg_iptm": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6},
        "min_interface_plddt": {"type": "number", "minimum": 0, "maximum": 100, "default": 87.0},
        "max_interface_pae": {"type": "number", "minimum": 0, "default": 10.0},
        "min_avg_model_support": {"type": "number", "minimum": 0, "default": 2.5},
        "min_contact_reproducibility": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
        "min_contact_jaccard": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.3},
        "max_iptm_stddev": {"type": "number", "minimum": 0, "default": 0.1},
        "min_iptm_margin": {"type": "number", "minimum": 0, "default": 0.1},
        "min_combo_margin": {"type": "number", "minimum": 0, "default": 0.03},
        "min_interface_pae_margin": {"type": "number", "minimum": 0, "default": 2.0},
        "session_id": {"type": "string"},
    },
    "required": [
        "candidate_afm_score_path",
        "negative_control_afm_score_path",
        "candidate_qc_path",
    ],
}


@registry.register(
    name="analysis.gpcr_candidate_qc",
    display_name="GPCR nanobody candidate QC",
    description=(
        "Evaluate a generated nanobody-GPCR complex against its exact mapped epitope and "
        "not-binding controls. Reports reference-calibrated BSA/clashes, interface and CDR3 "
        "confidence, intended-hotspot mapping/satisfaction, forbidden-face contacts, and a "
        "strict structural-triage gate."
    ),
    category="analysis",
    parameters=_PARAMETERS,
    usage_guide=(
        "Run on every final BoltzGen structure before orthogonal AF-M confirmation. Calibrate "
        "BSA/clash bounds against a known complex for the same target, face, and state. Reject "
        "missing confidence, forbidden contacts, or incomplete hotspot mapping. A pass means "
        "eligible for five-model AF-M confirmation, never confirmed binding."
    ),
)
def gpcr_candidate_qc(
    *,
    complex_path: str,
    target_manifest_path: str,
    binder_chain: str = "B",
    target_chain: str = "A",
    target_numbering: str = "manifest_label",
    cdr_ranges: str | None = None,
    design_mask_path: str | None = None,
    min_bsa: float = 1000.0,
    max_bsa: float = 3200.0,
    min_hotspot_satisfaction: float = 0.5,
    min_mapped_hotspot_fraction: float = 0.9,
    max_clash_score: float = 5.0,
    min_cdr_contact_fraction: float = 0.6,
    min_interface_confidence: float = 0.7,
    min_h3_confidence: float = 0.7,
    confidence_policy: str = "required",
    reference_complex_path: str | None = None,
    reference_binder_chain: str = "B",
    reference_target_chain: str = "A",
    reference_cdr_ranges: str | None = None,
    reference_bsa_min_ratio: float = 0.65,
    reference_bsa_max_ratio: float = 1.35,
    reference_clash_tolerance: float = 3.0,
    reference_cdr_tolerance: float = 0.05,
    **_: Any,
) -> dict[str, Any]:
    manifest_path = Path(target_manifest_path).expanduser().resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if int(manifest.get("schema_version", 0)) < 2:
            raise ValueError("schema v2 or newer is required")
        if manifest.get("mapping_verified") is not True:
            raise ValueError("canonical residue mapping is not verified")
        if target_numbering == "manifest_label":
            hotspots = [int(value) for value in manifest["binding_residues_label"]]
            excluded = {int(value) for value in manifest["excluded_residues_label"]}
            prediction_to_author: dict[int, int] = {}
        elif target_numbering == "manifest_author":
            hotspots = [int(value) for value in manifest["binding_residues_author"]]
            excluded = {int(value) for value in manifest["excluded_residues_author"]}
            prediction_to_author = {value: value for value in (*hotspots, *excluded)}
        elif target_numbering == "prediction_sequence":
            author_to_prediction = _prediction_sequence_residue_map(manifest_path, manifest)
            author_hotspots = [int(value) for value in manifest["binding_residues_author"]]
            author_excluded = [int(value) for value in manifest["excluded_residues_author"]]
            missing = sorted(
                value
                for value in (*author_hotspots, *author_excluded)
                if value not in author_to_prediction
            )
            if missing:
                raise ValueError(
                    "prepared target does not resolve prediction-sequence controls: "
                    + ",".join(map(str, missing))
                )
            hotspots = [author_to_prediction[value] for value in author_hotspots]
            excluded = {author_to_prediction[value] for value in author_excluded}
            prediction_to_author = {
                prediction: author for author, prediction in author_to_prediction.items()
            }
        else:
            raise ValueError(f"unsupported target_numbering {target_numbering!r}")
        if len(hotspots) < 2 or len(excluded) < 2:
            raise ValueError("mapped binding and not-binding controls are required")
        if min_bsa > max_bsa:
            raise ValueError("min_bsa cannot exceed max_bsa")
        for name, value in (
            ("min_hotspot_satisfaction", min_hotspot_satisfaction),
            ("min_mapped_hotspot_fraction", min_mapped_hotspot_fraction),
            ("min_cdr_contact_fraction", min_cdr_contact_fraction),
            ("min_interface_confidence", min_interface_confidence),
            ("min_h3_confidence", min_h3_confidence),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if reference_bsa_min_ratio > reference_bsa_max_ratio:
            raise ValueError("reference_bsa_min_ratio cannot exceed reference_bsa_max_ratio")
        if confidence_policy not in {"required", "external_confirmation"}:
            raise ValueError(f"unsupported confidence_policy {confidence_policy!r}")
        if not 0 <= reference_cdr_tolerance <= 1:
            raise ValueError("reference_cdr_tolerance must be in [0, 1]")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {"summary": f"Error: invalid target manifest or gate: {exc}", "error": "invalid_args", "metrics": {}}

    try:
        if not cdr_ranges and not design_mask_path:
            raise ValueError("cdr_ranges or a BoltzGen design_mask_path is required")
        if design_mask_path:
            cdr_ranges = json.dumps(
                _cdr_ranges_from_design_mask(
                    complex_path,
                    design_mask_path,
                    binder_chain=binder_chain,
                    target_chain=target_chain,
                )
            )
        metrics = compute_interface_metrics(
            complex_path,
            binder_chain=binder_chain,
            target_chain=target_chain,
            hotspots=hotspots,
            cdr_ranges=cdr_ranges,
        )
    except (InterfaceMetricsError, KeyError, OSError, ValueError) as exc:
        return {"summary": f"Error: {exc}", "error": "invalid_args", "metrics": {}}

    contacted_target = set(metrics["interface_residue_ids_target"])
    forbidden_contacts = sorted(contacted_target & excluded)
    forbidden_contacts_author = sorted(
        prediction_to_author[value]
        for value in forbidden_contacts
        if value in prediction_to_author
    )
    mapped_hotspots = sum(item.get("satisfied") is not None for item in metrics["hotspot_detail"])
    mapped_hotspot_fraction = mapped_hotspots / len(hotspots)

    reference_metrics: dict[str, Any] | None = None
    effective_min_bsa = min_bsa
    effective_max_bsa = max_bsa
    effective_max_clash = max_clash_score
    effective_min_cdr = min_cdr_contact_fraction
    if reference_complex_path:
        try:
            reference_metrics = compute_interface_metrics(
                reference_complex_path,
                binder_chain=reference_binder_chain,
                target_chain=reference_target_chain,
                cdr_ranges=reference_cdr_ranges,
            )
            reference_bsa = float(reference_metrics["interface_bsa"])
            reference_clash = float(reference_metrics["clash_score"])
            effective_min_bsa = max(min_bsa, reference_bsa * reference_bsa_min_ratio)
            effective_max_bsa = min(max_bsa, reference_bsa * reference_bsa_max_ratio)
            effective_max_clash = min(max_clash_score, reference_clash + reference_clash_tolerance)
            reference_cdr = reference_metrics.get("cdr_contact_fraction")
            if reference_cdr is not None:
                effective_min_cdr = min(
                    min_cdr_contact_fraction,
                    max(0.0, float(reference_cdr) - reference_cdr_tolerance),
                )
            if effective_min_bsa > effective_max_bsa:
                raise ValueError("reference calibration produces empty BSA bounds")
        except (InterfaceMetricsError, KeyError, OSError, TypeError, ValueError) as exc:
            return {"summary": f"Error: invalid reference complex: {exc}", "error": "invalid_args", "metrics": {}}

    failures: list[str] = []
    satisfaction = metrics["hotspot_satisfaction"]
    if satisfaction is None or satisfaction < min_hotspot_satisfaction:
        failures.append("insufficient intended-hotspot satisfaction")
    if mapped_hotspot_fraction < min_mapped_hotspot_fraction:
        failures.append("incomplete intended-hotspot mapping")
    bsa = metrics["interface_bsa"]
    if bsa is None or not effective_min_bsa <= bsa <= effective_max_bsa:
        failures.append("interface BSA outside calibrated bounds")
    if metrics["clash_score"] > effective_max_clash:
        failures.append("excessive interfacial clashes")
    cdr_fraction = metrics["cdr_contact_fraction"]
    if cdr_fraction is None or cdr_fraction < effective_min_cdr:
        failures.append("interface is not sufficiently CDR-driven")
    geometry_failures = list(failures)
    interface_confidence = _confidence_fraction(metrics["interface_plddt"])
    h3_confidence = _confidence_fraction(metrics["h3_plddt"])
    if confidence_policy == "required":
        if interface_confidence is None or interface_confidence < min_interface_confidence:
            failures.append("low or missing interface confidence")
        if h3_confidence is None or h3_confidence < min_h3_confidence:
            failures.append("low or missing CDR3 confidence")
    else:
        interface_confidence = None
        h3_confidence = None
    if forbidden_contacts:
        failures.append("contacts forbidden GPCR-face residues")
        geometry_failures.append("contacts forbidden GPCR-face residues")

    geometry_passed = not geometry_failures
    passed = not failures and confidence_policy == "required"
    decision_label = "passes" if passed else "passes geometry-only" if geometry_passed else "fails"
    return {
        "summary": (
            f"GPCR candidate {decision_label} structural triage QC: "
            f"hotspots {0.0 if satisfaction is None else satisfaction:.0%}, BSA {bsa} Å², "
            f"clash {metrics['clash_score']}, {len(forbidden_contacts)} forbidden contact(s)"
        ),
        **metrics,
        "forbidden_contact_residues": forbidden_contacts,
        "forbidden_contact_residues_author": forbidden_contacts_author,
        "target_numbering": target_numbering,
        "mapped_hotspot_fraction": round(mapped_hotspot_fraction, 3),
        "interface_confidence": interface_confidence,
        "h3_confidence": h3_confidence,
        "reference_calibration": (
            {
                "complex_path": str(Path(reference_complex_path).expanduser().resolve()),
                "interface_bsa": reference_metrics["interface_bsa"],
                "clash_score": reference_metrics["clash_score"],
                "cdr_contact_fraction": reference_metrics.get("cdr_contact_fraction"),
            }
            if reference_metrics is not None and reference_complex_path is not None
            else None
        ),
        "gate_stage": "structural_triage",
        "confidence_policy": confidence_policy,
        "passes_geometry_gate": geometry_passed,
        "eligible_for_afm_confirmation": passed or geometry_passed,
        "passes_strict_gate": passed,
        "gate_failures": failures,
        "geometry_gate_failures": geometry_failures,
        "gate_thresholds": {
            "min_bsa": round(effective_min_bsa, 3),
            "max_bsa": round(effective_max_bsa, 3),
            "min_hotspot_satisfaction": min_hotspot_satisfaction,
            "min_mapped_hotspot_fraction": min_mapped_hotspot_fraction,
            "max_clash_score": round(effective_max_clash, 3),
            "min_cdr_contact_fraction": round(effective_min_cdr, 3),
            "min_interface_confidence": min_interface_confidence,
            "min_h3_confidence": min_h3_confidence,
            "max_forbidden_contacts": 0,
        },
        "metrics": {
            "interface_bsa": bsa,
            "hotspot_satisfaction": satisfaction,
            "mapped_hotspot_fraction": round(mapped_hotspot_fraction, 3),
            "clash_score": metrics["clash_score"],
            "forbidden_contacts": len(forbidden_contacts),
            "cdr_contact_fraction": cdr_fraction,
            "interface_confidence": interface_confidence,
            "h3_confidence": h3_confidence,
        },
        "notes": [
            *metrics["notes"],
            "A structural-triage pass only permits five-model AF-M confirmation; it is not evidence of binding.",
        ],
    }


@registry.register(
    name="analysis.gpcr_confirmation_gate",
    display_name="GPCR nanobody confirmation gate",
    description=(
        "Fail-closed final computational promotion gate combining structural GPCR QC, "
        "five-model AF-M reproducibility, and separation from a same-target negative control."
    ),
    category="analysis",
    parameters=_CONFIRMATION_PARAMETERS,
    usage_guide=(
        "Run the candidate and a matched negative control with five AF-M models, save both "
        "analysis.afm_screen_score results plus the candidate structural-QC result as JSON, "
        "then call this tool. Missing evidence fails; a pass remains a computational priority, "
        "not an experimentally validated binder."
    ),
)
def gpcr_confirmation_gate(
    *,
    candidate_afm_score_path: str,
    negative_control_afm_score_path: str,
    candidate_qc_path: str,
    min_models: int = 5,
    min_avg_iptm: float = 0.6,
    min_interface_plddt: float = 87.0,
    max_interface_pae: float = 10.0,
    min_avg_model_support: float = 2.5,
    min_contact_reproducibility: float = 0.5,
    min_contact_jaccard: float = 0.3,
    max_iptm_stddev: float = 0.1,
    min_iptm_margin: float = 0.1,
    min_combo_margin: float = 0.03,
    min_interface_pae_margin: float = 2.0,
    **_: Any,
) -> dict[str, Any]:
    try:
        candidate = _load_json_object(candidate_afm_score_path, "candidate AF-M score")
        control = _load_json_object(negative_control_afm_score_path, "negative-control AF-M score")
        structural_qc = _load_json_object(candidate_qc_path, "candidate structural QC")
        candidate_avg = candidate["avg_metrics"]
        control_avg = control["avg_metrics"]
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {"summary": f"Error: invalid confirmation evidence: {exc}", "error": "invalid_args", "metrics": {}}

    failures: list[str] = []
    if structural_qc.get("passes_strict_gate") is not True:
        failures.append("candidate failed structural-triage QC")
    for label, score in (("candidate", candidate), ("negative control", control)):
        if int(score.get("num_models_scored", 0)) < min_models:
            failures.append(f"{label} has fewer than {min_models} scored AF-M models")
        if score.get("missing_score_json_pdbs"):
            failures.append(f"{label} has AF-M models with missing score JSON")

    candidate_iptm = _number(candidate_avg.get("iptm"))
    candidate_plddt = _number(candidate_avg.get("avg_interface_plddt"))
    candidate_pae = _number(candidate_avg.get("avg_interface_pae"))
    candidate_support = _number(candidate.get("avg_model_support"))
    candidate_repro = _number(candidate.get("contact_reproducibility"))
    candidate_jaccard = _number(candidate.get("mean_pairwise_contact_jaccard"))
    candidate_iptm_stddev = _number(candidate.get("iptm_stddev"))
    candidate_combo = _number(candidate.get("combo_feature"))

    absolute_checks = (
        (candidate_iptm, lambda value: value >= min_avg_iptm, "low or missing mean AF-M ipTM"),
        (candidate_plddt, lambda value: value >= min_interface_plddt, "low or missing mean interface pLDDT"),
        (candidate_pae, lambda value: value <= max_interface_pae, "high or missing mean interface PAE"),
        (candidate_support, lambda value: value >= min_avg_model_support, "insufficient mean model contact support"),
        (candidate_repro, lambda value: value >= min_contact_reproducibility, "insufficient reproducible-contact fraction"),
        (candidate_jaccard, lambda value: value >= min_contact_jaccard, "AF-M models do not reproduce the same interface"),
        (candidate_iptm_stddev, lambda value: value <= max_iptm_stddev, "AF-M ipTM is unstable across models"),
        (candidate_combo, lambda value: value >= 0, "missing AF-M composite score"),
    )
    for value, predicate, message in absolute_checks:
        if value is None or not predicate(value):
            failures.append(message)

    control_iptm = _number(control_avg.get("iptm"))
    control_combo = _number(control.get("combo_feature"))
    control_pae = _number(control_avg.get("avg_interface_pae"))
    margins = {
        "iptm": None if candidate_iptm is None or control_iptm is None else candidate_iptm - control_iptm,
        "combo_feature": None if candidate_combo is None or control_combo is None else candidate_combo - control_combo,
        "interface_pae": None if candidate_pae is None or control_pae is None else control_pae - candidate_pae,
    }
    if control_iptm is None or margins["iptm"] is None or margins["iptm"] < min_iptm_margin:
        failures.append("candidate does not separate from control by AF-M ipTM")
    # A control with no modeled interface can legitimately have no combo/PAE;
    # otherwise require explicit candidate separation on both signals.
    if control_combo is not None and (margins["combo_feature"] is None or margins["combo_feature"] < min_combo_margin):
        failures.append("candidate does not separate from control by composite score")
    if control_pae is not None and (margins["interface_pae"] is None or margins["interface_pae"] < min_interface_pae_margin):
        failures.append("candidate does not separate from control by interface PAE")

    passed = not failures
    return {
        "summary": (
            f"GPCR candidate {'passes' if passed else 'fails'} final computational confirmation: "
            f"{len(failures)} failure(s), ipTM margin {_format_margin(margins['iptm'])}"
        ),
        "gate_stage": "orthogonal_confirmation",
        "passes_confirmation_gate": passed,
        "gate_failures": failures,
        "candidate_metrics": {
            "num_models_scored": candidate.get("num_models_scored"),
            "avg_iptm": candidate_iptm,
            "avg_interface_plddt": candidate_plddt,
            "avg_interface_pae": candidate_pae,
            "avg_model_support": candidate_support,
            "contact_reproducibility": candidate_repro,
            "mean_pairwise_contact_jaccard": candidate_jaccard,
            "iptm_stddev": candidate_iptm_stddev,
            "combo_feature": candidate_combo,
        },
        "control_metrics": {
            "num_models_scored": control.get("num_models_scored"),
            "avg_iptm": control_iptm,
            "avg_interface_pae": control_pae,
            "combo_feature": control_combo,
        },
        "control_margins": {key: None if value is None else round(value, 6) for key, value in margins.items()},
        "gate_thresholds": {
            "min_models": min_models,
            "min_avg_iptm": min_avg_iptm,
            "min_interface_plddt": min_interface_plddt,
            "max_interface_pae": max_interface_pae,
            "min_avg_model_support": min_avg_model_support,
            "min_contact_reproducibility": min_contact_reproducibility,
            "min_contact_jaccard": min_contact_jaccard,
            "max_iptm_stddev": max_iptm_stddev,
            "min_iptm_margin": min_iptm_margin,
            "min_combo_margin": min_combo_margin,
            "min_interface_pae_margin": min_interface_pae_margin,
        },
        "notes": [
            "This gate requires structural QC, five-model reproducibility, and a matched negative control.",
            "A pass is a computational experimental priority, not evidence of binding or affinity.",
        ],
        "metrics": {
            "avg_iptm": candidate_iptm,
            "contact_reproducibility": candidate_repro,
            "iptm_control_margin": margins["iptm"],
        },
    }


def _load_json_object(path: str, label: str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _prediction_sequence_residue_map(
    manifest_path: Path, manifest: dict[str, Any]
) -> dict[int, int]:
    """Map author residue numbers to 1-based resolved-sequence positions."""
    recorded = Path(str(manifest.get("prepared_pdb_path") or "prepared_gpcr.pdb"))
    candidates = (
        recorded,
        manifest_path.parent / recorded.name,
        manifest_path.parent / "prepared_gpcr.pdb",
    )
    prepared = next((path for path in candidates if path.is_file()), None)
    if prepared is None:
        raise ValueError("target manifest does not resolve prepared_pdb_path")
    chain_id = str(manifest.get("target_auth_chain") or manifest.get("target_chain") or "")
    if not chain_id:
        raise ValueError("target manifest is missing target_auth_chain")

    author_residues: list[int] = []
    seen: set[tuple[int, str]] = set()
    for line in prepared.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27 or line[21].strip() != chain_id:
            continue
        try:
            author_residue = int(line[22:26])
        except ValueError:
            continue
        key = (author_residue, line[26].strip())
        if key in seen:
            continue
        seen.add(key)
        author_residues.append(author_residue)
    if not author_residues:
        raise ValueError(f"prepared target has no residues on author chain {chain_id!r}")
    if len(author_residues) != len(set(author_residues)):
        raise ValueError("prediction-sequence mapping does not support insertion-coded residues")
    return {author: index for index, author in enumerate(author_residues, start=1)}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _format_margin(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _confidence_fraction(value: Any) -> float | None:
    """Normalize model confidence from native 0..1 or pLDDT-style 0..100."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 <= number <= 100:
        return None
    return round(number if number <= 1 else number / 100.0, 3)


def _cdr_ranges_from_design_mask(
    complex_path: str,
    design_mask_path: str,
    *,
    binder_chain: str,
    target_chain: str,
) -> dict[str, list[int]]:
    import numpy as np
    from Bio.PDB import MMCIFParser, PDBParser

    path = Path(complex_path).expanduser().resolve()
    parser = MMCIFParser(QUIET=True) if path.suffix.lower() in {".cif", ".mmcif"} else PDBParser(QUIET=True)
    model = parser.get_structure("candidate", str(path))[0]
    for chain in (target_chain, binder_chain):
        if chain not in model:
            raise ValueError(f"chain {chain!r} is absent from candidate complex")
    target_length = len([residue for residue in model[target_chain] if residue.id[0] == " "])
    binder_length = len([residue for residue in model[binder_chain] if residue.id[0] == " "])
    with np.load(Path(design_mask_path).expanduser().resolve()) as payload:
        mask = payload["design_mask"]
    if len(mask) < target_length + binder_length:
        raise ValueError("BoltzGen design mask is shorter than the candidate chains")
    positions = [index + 1 for index, value in enumerate(mask[target_length : target_length + binder_length]) if value > 0.5]
    groups: list[list[int]] = []
    for position in positions:
        if not groups or position != groups[-1][-1] + 1:
            groups.append([position])
        else:
            groups[-1].append(position)
    if len(groups) != 3:
        raise ValueError(f"expected three CDR design-mask segments, found {len(groups)}")
    return {
        name: [group[0], group[-1]]
        for name, group in zip(("cdr1", "cdr2", "cdr3"), groups, strict=True)
    }


__all__ = ["gpcr_candidate_qc", "gpcr_confirmation_gate"]
