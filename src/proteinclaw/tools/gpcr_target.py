"""Prepare an intact, state-specific GPCR target for nanobody design.

The agent is responsible for researching the receptor, state, binding side,
and epitope.  This tool turns that adjudicated hypothesis into a validated,
traceable target manifest; it deliberately does not guess those scientific
choices or crop disconnected extracellular loops from a seven-TM receptor.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
import shutil
from pathlib import Path
from typing import Any, Optional

from proteinclaw.tools import registry
from proteinclaw.tools._paths import tool_output_dir
from proteinclaw.tools.pdb import _filter_pdb, _line_chain, _line_resi

_RESIDUE_LIST_RE = re.compile(r"^\s*\d+(?:\s*,\s*\d+)*\s*$")
_SPAN_LIST_RE = re.compile(r"^\s*\d+\s*-\s*\d+(?:\s*,\s*\d+\s*-\s*\d+)*\s*$")

_EVIDENCE_TYPES = {
    "complex_structure",
    "mutagenesis",
    "binding_assay",
    "functional_assay",
    "crosslinking_hdx",
    "homolog_structure",
}
_EVIDENCE_DIRECTNESS = {
    "direct_same_receptor",
    "same_receptor_indirect",
    "homolog_transfer",
}

_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "citation": {
            "type": "string",
            "minLength": 3,
            "description": "DOI, PMID, PDB ID, or stable URL supporting this claim.",
        },
        "evidence_type": {"type": "string", "enum": sorted(_EVIDENCE_TYPES)},
        "directness": {"type": "string", "enum": sorted(_EVIDENCE_DIRECTNESS)},
        "claim": {"type": "string", "minLength": 15},
    },
    "required": ["citation", "evidence_type", "directness", "claim"],
}

_STATE_MARKER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 2},
        "residues": {
            "type": "string",
            "pattern": "^\\s*\\d+(?:\\s*,\\s*\\d+)*\\s*$",
            "description": "Resolved author-numbered residues inspected for this marker.",
        },
        "observation": {"type": "string", "minLength": 10},
        "supports_state": {
            "type": "string",
            "enum": ["active", "inactive", "intermediate", "ambiguous"],
        },
    },
    "required": ["name", "residues", "observation", "supports_state"],
}

_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "target_pdb": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Optional local legacy PDB path. When omitted, target_mmcif is converted with "
                "author chain and residue numbering preserved."
            ),
        },
        "target_mmcif": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Original RCSB mmCIF for canonical auth_seq_id to label_seq_id mapping. "
                "Required for generative design."
            ),
        },
        "target_chain": {
            "type": "string",
            "pattern": "^[A-Za-z0-9]$",
            "description": "One-character GPCR author chain in target_mmcif/target_pdb.",
        },
        "binding_side": {
            "type": "string",
            "enum": ["extracellular", "intracellular"],
            "description": "Biological side the nanobody must bind.",
        },
        "receptor_state": {
            "type": "string",
            "enum": ["active", "inactive", "intermediate", "unknown"],
            "description": "Adjudicated GPCR conformational state.",
        },
        "binding_residues": {
            "type": "string",
            "pattern": "^\\s*\\d+(?:\\s*,\\s*\\d+)*\\s*$",
            "description": "Two to twelve epitope residue numbers on target_chain, e.g. '147,150,232'.",
        },
        "excluded_residues": {
            "type": "string",
            "pattern": "^\\s*\\d+(?:\\s*,\\s*\\d+)*\\s*$",
            "description": "Residues that designs must not contact, such as the opposite receptor face.",
        },
        "membrane_spans": {
            "type": "string",
            "pattern": "^\\s*\\d+\\s*-\\s*\\d+(?:\\s*,\\s*\\d+\\s*-\\s*\\d+)*\\s*$",
            "description": (
                "Author-numbered membrane-core spans, e.g. '75-97,105-127'. "
                "Binding anchors inside these spans are rejected."
            ),
        },
        "epitope_rationale": {
            "type": "string",
            "minLength": 20,
            "description": "Evidence-backed explanation recorded with the target hypothesis.",
        },
        "state_rationale": {
            "type": "string",
            "minLength": 20,
            "description": "Evidence for the selected receptor state and any retained ligand/cofactor assumptions.",
        },
        "source_id": {
            "type": "string",
            "description": "Optional PDB/UniProt/GPCRdb identifier for provenance.",
        },
        "receptor_id": {
            "type": "string",
            "minLength": 2,
            "description": "Stable receptor identity shared across an ensemble, e.g. UniProt P35372.",
        },
        "hypothesis_id": {
            "type": "string",
            "pattern": "^[a-z0-9][a-z0-9_-]{1,63}$",
            "description": "ID from the adjudicated hypothesis portfolio.",
        },
        "hypothesis_portfolio_path": {
            "type": "string",
            "minLength": 1,
            "description": "Optional portfolio manifest used to verify state, side, anchors, and evidence.",
        },
        "structure_method": {
            "type": "string",
            "enum": ["xray", "cryo_em", "nmr", "predicted", "hybrid"],
        },
        "structure_resolution_angstrom": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "Experimental resolution when applicable; omit for predicted structures.",
        },
        "construct_context": {
            "type": "string",
            "minLength": 20,
            "description": "Mutations, truncations, fusion partners, missing termini, and expression construct caveats.",
        },
        "ligand_context": {
            "type": "string",
            "minLength": 10,
            "description": "Bound agonist/antagonist, ions, G protein or nanobody stabilization, and what is retained.",
        },
        "membrane_span_source": {
            "type": "string",
            "minLength": 5,
            "description": "Citation or database/version used for the seven transmembrane ranges.",
        },
        "unresolved_regions": {
            "type": "string",
            "pattern": "^\\s*(?:\\d+\\s*-\\s*\\d+(?:\\s*,\\s*\\d+\\s*-\\s*\\d+)*)?\\s*$",
            "description": "Expected author-numbered regions with no coordinates; empty string means none.",
        },
        "modeled_regions": {
            "type": "string",
            "pattern": "^\\s*(?:\\d+\\s*-\\s*\\d+(?:\\s*,\\s*\\d+\\s*-\\s*\\d+)*)?\\s*$",
            "description": "Author-numbered coordinates added by modelling; empty string means none.",
        },
        "glycosylation_sites": {
            "type": "string",
            "pattern": "^\\s*(?:\\d+(?:\\s*,\\s*\\d+)*)?\\s*$",
            "description": "Known or observed author-numbered glycosylation sites; empty string means none.",
        },
        "state_markers": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": _STATE_MARKER_SCHEMA,
            "description": "Resolved activation microswitch observations supporting the state assignment.",
        },
        "experimental_evidence": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": _EVIDENCE_SCHEMA,
            "description": "Experimental evidence grounding the state and epitope hypothesis.",
        },
        "reference_complex_ids": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "minLength": 3},
            "description": "Same-receptor or homolog experimental complexes used for interface calibration.",
        },
        "reference_scaffold_ids": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "minLength": 3},
            "description": "Experimentally observed VHH/scaffold structures relevant to the intended face.",
        },
        "counterstate_source_ids": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "minLength": 3},
            "description": "Active/inactive/intermediate comparator structures for state-ensemble controls.",
        },
        "confirmation_strategy": {
            "type": "string",
            "enum": [
                "structure_conditioned",
                "state_specific_construct",
                "sequence_only_state_uncontrolled"
            ],
            "description": "Whether downstream confirmation preserves the adjudicated receptor conformation.",
        },
        "session_id": {"type": "string"},
        "step": {"type": "integer", "minimum": 0, "default": 0},
    },
    "required": [
        "target_mmcif",
        "target_chain",
        "binding_side",
        "receptor_state",
        "binding_residues",
        "excluded_residues",
        "membrane_spans",
        "epitope_rationale",
        "state_rationale",
        "source_id",
        "receptor_id",
        "hypothesis_id",
        "structure_method",
        "construct_context",
        "ligand_context",
        "membrane_span_source",
        "unresolved_regions",
        "modeled_regions",
        "glycosylation_sites",
        "state_markers",
        "experimental_evidence",
        "reference_complex_ids",
        "reference_scaffold_ids",
        "counterstate_source_ids",
        "confirmation_strategy",
    ],
}

_HYPOTHESIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "hypothesis_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{1,63}$"},
        "target_source_id": {"type": "string", "minLength": 3},
        "target_chain": {"type": "string", "pattern": "^[A-Za-z0-9]$"},
        "receptor_state": {"type": "string", "enum": ["active", "inactive", "intermediate", "unknown"]},
        "binding_side": {"type": "string", "enum": ["extracellular", "intracellular"]},
        "binding_residues": {"type": "string", "pattern": "^\\s*\\d+(?:\\s*,\\s*\\d+)*\\s*$"},
        "excluded_residues": {"type": "string", "pattern": "^\\s*\\d+(?:\\s*,\\s*\\d+)*\\s*$"},
        "epitope_rationale": {"type": "string", "minLength": 20},
        "state_rationale": {"type": "string", "minLength": 20},
        "falsifiable_prediction": {"type": "string", "minLength": 20},
        "dominant_risk": {"type": "string", "minLength": 20},
        "distinguishing_variable": {
            "type": "string",
            "enum": ["receptor_state", "epitope", "approach_vector", "construct", "scaffold_regime"],
        },
        "expected_information_gain": {"type": "string", "enum": ["high", "medium", "low"]},
        "experimental_evidence": {"type": "array", "minItems": 1, "maxItems": 20, "items": _EVIDENCE_SCHEMA},
        "reference_complex_ids": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "string", "minLength": 3}},
        "reference_scaffold_ids": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "string", "minLength": 3}},
        "counterstate_source_ids": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "string", "minLength": 3}},
        "confirmation_strategy": {
            "type": "string",
            "enum": ["structure_conditioned", "state_specific_construct", "sequence_only_state_uncontrolled"],
        },
        "negative_control": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "control_type": {
                    "type": "string",
                    "enum": ["wrong_face", "state_mismatch", "unrelated_vhh", "scrambled_vhh"],
                },
                "description": {"type": "string", "minLength": 15},
                "discriminating_result": {"type": "string", "minLength": 15},
            },
            "required": ["control_type", "description", "discriminating_result"],
        },
    },
    "required": [
        "hypothesis_id", "target_source_id", "target_chain", "receptor_state", "binding_side",
        "binding_residues", "excluded_residues", "epitope_rationale", "state_rationale",
        "falsifiable_prediction", "dominant_risk", "distinguishing_variable",
        "expected_information_gain", "experimental_evidence", "reference_complex_ids",
        "reference_scaffold_ids", "counterstate_source_ids", "confirmation_strategy", "negative_control"
    ],
}

_PORTFOLIO_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "receptor_id": {"type": "string", "minLength": 2},
        "hypotheses": {"type": "array", "minItems": 2, "maxItems": 8, "items": _HYPOTHESIS_SCHEMA},
        "exploration_designs_per_hypothesis": {"type": "integer", "minimum": 2, "maximum": 6, "default": 4},
        "max_total_exploration_designs": {"type": "integer", "minimum": 4, "maximum": 48, "default": 24},
        "deep_dive_design_budget": {"type": "integer", "minimum": 4, "maximum": 16, "default": 8},
        "session_id": {"type": "string"},
        "step": {"type": "integer", "minimum": 0, "default": 0},
    },
    "required": ["receptor_id", "hypotheses"],
}


def _parse_residues(raw: Optional[str], *, field: str) -> list[int]:
    if not raw or not raw.strip():
        return []
    if not _RESIDUE_LIST_RE.match(raw):
        raise ValueError(f"{field} must be a comma-separated integer list")
    return list(dict.fromkeys(int(token.strip()) for token in raw.split(",")))


def _present_residues(text: str, chain: str) -> set[int]:
    return {
        resi
        for line in text.splitlines()
        if line.startswith("ATOM  ") and _line_chain(line) == chain
        if (resi := _line_resi(line)) is not None
    }


def _parse_spans(raw: Optional[str]) -> list[tuple[int, int]]:
    if not raw or not _SPAN_LIST_RE.match(raw):
        raise ValueError("membrane_spans must be comma-separated start-end ranges")
    spans: list[tuple[int, int]] = []
    for token in raw.split(","):
        start, end = (int(value.strip()) for value in token.split("-", 1))
        if start >= end:
            raise ValueError("each membrane span must have start < end")
        spans.append((start, end))
    if len(spans) != 7:
        raise ValueError("membrane_spans must contain exactly seven ordered TM-core ranges")
    if spans != sorted(spans) or any(left[1] >= right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError("membrane_spans must be ordered and non-overlapping")
    return spans


def _parse_optional_spans(raw: Optional[str], *, field: str) -> list[tuple[int, int]]:
    if raw is None or not raw.strip():
        return []
    if not _SPAN_LIST_RE.match(raw):
        raise ValueError(f"{field} must be empty or comma-separated start-end ranges")
    spans: list[tuple[int, int]] = []
    for token in raw.split(","):
        start, end = (int(value.strip()) for value in token.split("-", 1))
        if start > end:
            raise ValueError(f"each {field} span must have start <= end")
        spans.append((start, end))
    if spans != sorted(spans) or any(left[1] >= right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError(f"{field} spans must be ordered and non-overlapping")
    return spans


def _span_residues(spans: list[tuple[int, int]]) -> set[int]:
    return {residue for start, end in spans for residue in range(start, end + 1)}


def _validate_experimental_evidence(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("experimental_evidence must contain at least one evidence record")
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"experimental_evidence[{index}] must be an object")
        missing = {"citation", "evidence_type", "directness", "claim"} - item.keys()
        if missing:
            raise ValueError(f"experimental_evidence[{index}] lacks {sorted(missing)}")
        evidence_type = str(item["evidence_type"]).strip()
        directness = str(item["directness"]).strip()
        citation = str(item["citation"]).strip()
        claim = str(item["claim"]).strip()
        if evidence_type not in _EVIDENCE_TYPES:
            raise ValueError(f"experimental_evidence[{index}] has unsupported evidence_type")
        if directness not in _EVIDENCE_DIRECTNESS:
            raise ValueError(f"experimental_evidence[{index}] has unsupported directness")
        if len(citation) < 3 or len(claim) < 15:
            raise ValueError(f"experimental_evidence[{index}] citation/claim is too short")
        normalized.append(
            {
                "citation": citation,
                "evidence_type": evidence_type,
                "directness": directness,
                "claim": claim,
            }
        )
    return normalized


def _validate_state_markers(raw: Any, present: set[int], receptor_state: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("state_markers must contain at least one resolved marker")
    normalized: list[dict[str, Any]] = []
    supported = False
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"state_markers[{index}] must be an object")
        missing = {"name", "residues", "observation", "supports_state"} - item.keys()
        if missing:
            raise ValueError(f"state_markers[{index}] lacks {sorted(missing)}")
        residues = _parse_residues(str(item["residues"]), field=f"state_markers[{index}].residues")
        absent = sorted(set(residues) - present)
        if absent:
            raise ValueError(f"state_markers[{index}] references unresolved residues: {absent}")
        supports_state = str(item["supports_state"]).strip()
        if supports_state not in {"active", "inactive", "intermediate", "ambiguous"}:
            raise ValueError(f"state_markers[{index}] has unsupported state assignment")
        if supports_state == receptor_state:
            supported = True
        normalized.append(
            {
                "name": str(item["name"]).strip(),
                "residues_author": residues,
                "observation": str(item["observation"]).strip(),
                "supports_state": supports_state,
            }
        )
    if receptor_state != "unknown" and not supported:
        raise ValueError(f"no state marker explicitly supports receptor_state={receptor_state!r}")
    return normalized


def _normalized_ids(raw: Optional[list[str]], *, field: str) -> list[str]:
    if raw is None:
        raise ValueError(f"{field} must be supplied explicitly (use [] when none are available)")
    if not isinstance(raw, list):
        raise ValueError(f"{field} must be a list")
    values = list(dict.fromkeys(str(value).strip() for value in raw))
    if any(len(value) < 3 for value in values):
        raise ValueError(f"{field} entries must contain at least three characters")
    return values


def _verify_portfolio_link(
    path: Optional[str],
    *,
    hypothesis_id: str,
    receptor_id: str,
    receptor_state: str,
    binding_side: str,
    hotspots: list[int],
    excluded: list[int],
) -> Optional[str]:
    if not path:
        return None
    portfolio_path = Path(path).expanduser().resolve()
    try:
        portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read hypothesis_portfolio_path: {exc}") from exc
    if int(portfolio.get("schema_version", 0)) < 1:
        raise ValueError("hypothesis portfolio has unsupported schema_version")
    if portfolio.get("receptor_id") != receptor_id:
        raise ValueError("hypothesis portfolio receptor_id does not match target")
    matches = [item for item in portfolio.get("hypotheses", []) if item.get("hypothesis_id") == hypothesis_id]
    if len(matches) != 1:
        raise ValueError(f"hypothesis portfolio does not contain unique hypothesis_id={hypothesis_id!r}")
    item = matches[0]
    expected = {
        "receptor_state": receptor_state,
        "binding_side": binding_side,
        "binding_residues": hotspots,
        "excluded_residues": excluded,
    }
    mismatches = [key for key, value in expected.items() if item.get(key) != value]
    if mismatches:
        raise ValueError(f"target disagrees with portfolio hypothesis fields: {mismatches}")
    return str(portfolio_path)


def _face_topology(
    text: str,
    chain: str,
    spans: list[tuple[int, int]],
    hotspots: list[int],
    excluded: list[int],
    binding_side: str,
) -> dict[str, Any]:
    """Estimate the extracellular-to-intracellular axis from seven TM helices."""
    ca: dict[int, tuple[float, float, float]] = {}
    for line in text.splitlines():
        if not line.startswith("ATOM  ") or _line_chain(line) != chain:
            continue
        if line[12:16].strip() != "CA":
            continue
        residue = _line_resi(line)
        if residue is None:
            continue
        try:
            ca[residue] = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError:
            continue

    vectors: list[tuple[float, float, float]] = []
    for index, (start, end) in enumerate(spans):
        present = sorted(residue for residue in ca if start <= residue <= end)
        if len(present) < 2:
            raise ValueError(f"TM{index + 1} has fewer than two resolved CA atoms")
        first, last = ca[present[0]], ca[present[-1]]
        vector = tuple(last[axis] - first[axis] for axis in range(3))
        if index % 2:
            vector = tuple(-value for value in vector)
        length = math.sqrt(sum(value * value for value in vector))
        if length == 0:
            raise ValueError(f"TM{index + 1} has a degenerate coordinate axis")
        vectors.append(tuple(value / length for value in vector))
    normal = tuple(sum(vector[axis] for vector in vectors) / len(vectors) for axis in range(3))
    length = math.sqrt(sum(value * value for value in normal))
    if length < 0.1:
        raise ValueError("seven-TM axes do not define a stable membrane normal")
    normal = tuple(value / length for value in normal)

    def mean_projection(residues: list[int]) -> float:
        return sum(sum(ca[value][axis] * normal[axis] for axis in range(3)) for value in residues) / len(residues)

    try:
        positive_mean = mean_projection(hotspots)
        excluded_mean = mean_projection(excluded)
    except KeyError as exc:
        raise ValueError(f"face-control residue {exc.args[0]} has no resolved CA atom") from exc
    signed_separation = positive_mean - excluded_mean
    if binding_side == "extracellular":
        signed_separation = -signed_separation
    if signed_separation < 8.0:
        raise ValueError(
            f"positive and excluded residues do not separate onto the requested {binding_side} face "
            f"({signed_separation:.2f} A)"
        )
    return {
        "membrane_normal_e_to_i": [round(value, 6) for value in normal],
        "positive_face_projection": round(positive_mean, 3),
        "excluded_face_projection": round(excluded_mean, 3),
        "face_separation_angstrom": round(signed_separation, 3),
    }


def _mmcif_numbering(path: Path, auth_chain: str) -> tuple[str, dict[int, int]]:
    """Return the unique label chain and author->label residue mapping."""
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict

    data = MMCIF2Dict(str(path))
    required = (
        "_atom_site.group_PDB",
        "_atom_site.auth_asym_id",
        "_atom_site.label_asym_id",
        "_atom_site.auth_seq_id",
        "_atom_site.label_seq_id",
    )
    if any(key not in data for key in required):
        raise ValueError("mmCIF lacks required atom_site author/label numbering columns")
    mapping: dict[int, int] = {}
    label_chains: set[str] = set()
    rows = zip(*(data[key] for key in required), strict=True)
    for group, auth_asym, label_asym, auth_seq, label_seq in rows:
        if group != "ATOM" or auth_asym != auth_chain:
            continue
        if auth_seq in {".", "?"} or label_seq in {".", "?"}:
            continue
        auth_id, label_id = int(auth_seq), int(label_seq)
        previous = mapping.setdefault(auth_id, label_id)
        if previous != label_id:
            raise ValueError(f"ambiguous mmCIF mapping for author residue {auth_id}")
        label_chains.add(label_asym)
    if not mapping:
        raise ValueError(f"mmCIF has no ATOM records for author chain {auth_chain!r}")
    if len(label_chains) != 1:
        raise ValueError(f"author chain {auth_chain!r} maps to multiple label chains: {sorted(label_chains)}")
    return next(iter(label_chains)), mapping


def _mmcif_chain_to_pdb(path: Path, output_path: Path, auth_chain: str) -> None:
    """Write one author-numbered mmCIF chain as a legacy-PDB compatibility view.

    The original mmCIF remains authoritative for label/auth mapping.  Selecting
    only the requested author chain avoids PDB's one-character chain limitation
    for unrelated assembly partners while retaining receptor HETATM records.
    """
    from Bio.PDB import MMCIFParser, PDBIO, Select
    from Bio.PDB.PDBExceptions import PDBException

    try:
        structure = MMCIFParser(QUIET=True, auth_chains=True, auth_residues=True).get_structure(
            path.stem,
            str(path),
        )
    except (KeyError, OSError, PDBException, TypeError, ValueError) as exc:
        raise ValueError(f"could not parse author-numbered mmCIF coordinates: {exc}") from exc
    chains = {chain.id for model in structure for chain in model}
    if auth_chain not in chains:
        raise ValueError(
            f"mmCIF has no author chain {auth_chain!r}; available author chains: {sorted(chains)}"
        )

    class _ChainSelect(Select):
        def accept_chain(self, chain: Any) -> bool:
            return chain.id == auth_chain

    writer = PDBIO()
    writer.set_structure(structure)
    try:
        writer.save(str(output_path), select=_ChainSelect(), preserve_atom_numbering=False)
    except (OSError, PDBException) as exc:
        raise ValueError(f"could not create author-numbered PDB compatibility view: {exc}") from exc
    if not output_path.exists() or not _present_residues(
        output_path.read_text(encoding="utf-8", errors="replace"), auth_chain
    ):
        raise ValueError(f"converted mmCIF chain {auth_chain!r} contains no protein atoms")


def _evidence_strength(records: list[dict[str, str]]) -> int:
    type_weight = {
        "complex_structure": 5,
        "mutagenesis": 4,
        "binding_assay": 4,
        "functional_assay": 3,
        "crosslinking_hdx": 3,
        "homolog_structure": 2,
    }
    directness_weight = {
        "direct_same_receptor": 3,
        "same_receptor_indirect": 2,
        "homolog_transfer": 0,
    }
    return sum(type_weight[item["evidence_type"]] + directness_weight[item["directness"]] for item in records)


@registry.register(
    name="data.gpcr_hypothesis_portfolio",
    display_name="Build an evidence-grounded GPCR hypothesis portfolio",
    description=(
        "Validate 2-8 structurally distinct GPCR nanobody hypotheses, their experimental evidence, "
        "counterstate/reference structures, falsifiable predictions, and matched controls. Produces "
        "a small exploration wave and a gated deep-dive policy."
    ),
    category="data",
    parameters=_PORTFOLIO_PARAMETERS,
    usage_guide=(
        "Call after research fan-out and before target preparation. Explore several hypotheses with "
        "2-6 designs each; only use the larger deep-dive budget after a hypothesis beats its matched control."
    ),
)
def gpcr_hypothesis_portfolio(
    *,
    receptor_id: str,
    hypotheses: list[dict[str, Any]],
    exploration_designs_per_hypothesis: int = 4,
    max_total_exploration_designs: int = 24,
    deep_dive_design_budget: int = 8,
    session_id: Optional[str] = None,
    step: int = 0,
    **_: Any,
) -> dict[str, Any]:
    if len(receptor_id.strip()) < 2:
        return {"summary": "Error: receptor_id is required", "error": "invalid_args", "metrics": {}}
    if not 2 <= len(hypotheses) <= 8:
        return {"summary": "Error: hypotheses must contain 2-8 entries", "error": "invalid_args", "metrics": {}}
    if not 2 <= exploration_designs_per_hypothesis <= 6:
        return {"summary": "Error: exploration budget must be 2-6 per hypothesis", "error": "invalid_args", "metrics": {}}
    if not 4 <= deep_dive_design_budget <= 16:
        return {"summary": "Error: deep-dive budget must be 4-16", "error": "invalid_args", "metrics": {}}
    required_total = len(hypotheses) * exploration_designs_per_hypothesis
    if required_total > max_total_exploration_designs:
        return {
            "summary": (
                f"Error: exploration requires {required_total} designs but max_total_exploration_designs="
                f"{max_total_exploration_designs}; reduce per-hypothesis depth, not hypothesis diversity"
            ),
            "error": "invalid_args",
            "metrics": {},
        }

    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    fingerprints: set[str] = set()
    direct_evidence_total = 0
    try:
        for index, raw in enumerate(hypotheses):
            if not isinstance(raw, dict):
                raise ValueError(f"hypotheses[{index}] must be an object")
            hypothesis_id = str(raw.get("hypothesis_id", "")).strip()
            if not re.match(r"^[a-z0-9][a-z0-9_-]{1,63}$", hypothesis_id):
                raise ValueError(f"hypotheses[{index}] has invalid hypothesis_id")
            if hypothesis_id in ids:
                raise ValueError(f"duplicate hypothesis_id={hypothesis_id!r}")
            ids.add(hypothesis_id)
            hotspots = _parse_residues(raw.get("binding_residues"), field=f"hypotheses[{index}].binding_residues")
            excluded = _parse_residues(raw.get("excluded_residues"), field=f"hypotheses[{index}].excluded_residues")
            if not 2 <= len(hotspots) <= 12 or not 2 <= len(excluded) <= 32:
                raise ValueError(f"hypotheses[{index}] requires 2-12 anchors and 2-32 exclusions")
            if set(hotspots) & set(excluded):
                raise ValueError(f"hypotheses[{index}] has overlapping anchors and exclusions")
            evidence = _validate_experimental_evidence(raw.get("experimental_evidence"))
            direct_evidence_total += sum(item["directness"] == "direct_same_receptor" for item in evidence)
            references = _normalized_ids(raw.get("reference_complex_ids"), field="reference_complex_ids")
            scaffolds = _normalized_ids(raw.get("reference_scaffold_ids"), field="reference_scaffold_ids")
            counterstates = _normalized_ids(raw.get("counterstate_source_ids"), field="counterstate_source_ids")
            if not references or not scaffolds or not counterstates:
                raise ValueError(
                    f"hypotheses[{index}] must declare a reference complex, scaffold, and counterstate structure"
                )
            prediction = str(raw.get("falsifiable_prediction", "")).strip()
            risk = str(raw.get("dominant_risk", "")).strip()
            if len(prediction) < 20 or len(risk) < 20:
                raise ValueError(f"hypotheses[{index}] needs a falsifiable prediction and dominant risk")
            negative = raw.get("negative_control")
            if not isinstance(negative, dict) or any(
                not str(negative.get(key, "")).strip()
                for key in ("control_type", "description", "discriminating_result")
            ):
                raise ValueError(f"hypotheses[{index}] needs a complete matched negative_control")
            state = str(raw.get("receptor_state", "")).strip()
            side = str(raw.get("binding_side", "")).strip()
            source_id = str(raw.get("target_source_id", "")).strip()
            target_chain = str(raw.get("target_chain", "")).strip()
            if state not in {"active", "inactive", "intermediate", "unknown"}:
                raise ValueError(f"hypotheses[{index}] has unsupported receptor_state")
            if side not in {"extracellular", "intracellular"}:
                raise ValueError(f"hypotheses[{index}] has unsupported binding_side")
            if len(source_id) < 3 or not re.match(r"^[A-Za-z0-9]$", target_chain):
                raise ValueError(f"hypotheses[{index}] needs a target source and one-character chain")
            if len(str(raw.get("epitope_rationale", "")).strip()) < 20 or len(
                str(raw.get("state_rationale", "")).strip()
            ) < 20:
                raise ValueError(f"hypotheses[{index}] needs epitope and state rationales")
            fingerprint = hashlib.sha256(
                json.dumps(
                    {"state": state, "side": side, "anchors": hotspots, "exclusions": excluded},
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()[:16]
            if fingerprint in fingerprints:
                raise ValueError(f"hypotheses[{index}] duplicates an existing structural hypothesis")
            fingerprints.add(fingerprint)
            info_gain = str(raw.get("expected_information_gain", "")).strip()
            score = _evidence_strength(evidence) + {"high": 4, "medium": 2, "low": 0}.get(info_gain, -100)
            normalized.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "hypothesis_fingerprint": fingerprint,
                    "target_source_id": source_id,
                    "target_chain": target_chain,
                    "receptor_state": state,
                    "binding_side": side,
                    "binding_residues": hotspots,
                    "excluded_residues": excluded,
                    "epitope_rationale": str(raw.get("epitope_rationale", "")).strip(),
                    "state_rationale": str(raw.get("state_rationale", "")).strip(),
                    "falsifiable_prediction": prediction,
                    "dominant_risk": risk,
                    "distinguishing_variable": str(raw.get("distinguishing_variable", "")).strip(),
                    "expected_information_gain": info_gain,
                    "experimental_evidence": evidence,
                    "evidence_strength": score,
                    "reference_complex_ids": references,
                    "reference_scaffold_ids": scaffolds,
                    "counterstate_source_ids": counterstates,
                    "confirmation_strategy": str(raw.get("confirmation_strategy", "")).strip(),
                    "negative_control": negative,
                    "exploration_design_budget": exploration_designs_per_hypothesis,
                }
            )
    except ValueError as exc:
        return {"summary": f"Error: {exc}", "error": "invalid_args", "metrics": {}}

    diversity = {(item["receptor_state"], item["binding_side"], tuple(item["binding_residues"])) for item in normalized}
    if len(diversity) < 2:
        return {"summary": "Error: portfolio lacks structurally distinct hypotheses", "error": "invalid_args", "metrics": {}}
    if direct_evidence_total == 0:
        return {
            "summary": "Error: portfolio needs at least one direct same-receptor experimental evidence record",
            "error": "invalid_args",
            "metrics": {},
        }
    normalized.sort(key=lambda item: (-item["evidence_strength"], item["hypothesis_id"]))
    for rank, item in enumerate(normalized, start=1):
        item["exploration_rank"] = rank

    manifest = {
        "schema_version": 1,
        "receptor_id": receptor_id.strip(),
        "hypotheses": normalized,
        "exploration_policy": {
            "designs_per_hypothesis": exploration_designs_per_hypothesis,
            "total_design_budget": required_total,
            "wave_order": [item["hypothesis_id"] for item in normalized],
            "advance_all_before_deep_dive": True,
        },
        "promotion_gate": {
            "required": [
                "beats_matched_negative_control",
                "mapped_hotspot_and_exclusion_gate_passes",
                "physically_plausible_membrane_approach",
                "support_repeats_across_independent_models_or_seeds",
            ],
            "deep_dive_design_budget": deep_dive_design_budget,
            "maximum_promoted_hypotheses": 2,
            "sequence_only_state_warning": (
                "Sequence-only AF-M cannot establish state selectivity; require a state-preserving confirmation path."
            ),
        },
    }
    out_dir = tool_output_dir("gpcr_hypothesis_portfolio", session_id, step)
    path = out_dir / "hypothesis_portfolio.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "summary": (
            f"Prepared {len(normalized)} evidence-grounded hypotheses for {receptor_id}: "
            f"{required_total} total exploration designs before any deep dive"
        ),
        "hypothesis_portfolio_path": str(path),
        **manifest,
        "metrics": {
            "num_hypotheses": len(normalized),
            "exploration_design_budget": required_total,
            "direct_same_receptor_evidence_count": direct_evidence_total,
        },
        "session_id": session_id,
    }


@registry.register(
    name="data.gpcr_target_prepare",
    display_name="Prepare a GPCR nanobody target",
    description=(
        "Validate and stage an intact PDB- or mmCIF-sourced GPCR chain for a researched nanobody design hypothesis. "
        "Records receptor state, extracellular/intracellular side, epitope residues, exclusions, "
        "and rationale in a manifest consumed by generative design tools."
    ),
    category="data",
    parameters=_PARAMETERS,
    usage_guide=(
        "Call only after native research, structural due diligence, and debate have selected a "
        "state and epitope. Always pass mmCIF; legacy PDB is optional. Pass the full receptor chain; "
        "never substitute a disconnected loop-only crop."
    ),
)
def gpcr_target_prepare(
    *,
    target_pdb: Optional[str] = None,
    target_mmcif: Optional[str] = None,
    target_chain: str,
    binding_side: str,
    receptor_state: str,
    binding_residues: str,
    epitope_rationale: str,
    state_rationale: str,
    excluded_residues: Optional[str] = None,
    membrane_spans: Optional[str] = None,
    source_id: Optional[str] = None,
    receptor_id: Optional[str] = None,
    hypothesis_id: Optional[str] = None,
    hypothesis_portfolio_path: Optional[str] = None,
    structure_method: Optional[str] = None,
    structure_resolution_angstrom: Optional[float] = None,
    construct_context: Optional[str] = None,
    ligand_context: Optional[str] = None,
    membrane_span_source: Optional[str] = None,
    unresolved_regions: Optional[str] = None,
    modeled_regions: Optional[str] = None,
    glycosylation_sites: Optional[str] = None,
    state_markers: Optional[list[dict[str, Any]]] = None,
    experimental_evidence: Optional[list[dict[str, Any]]] = None,
    reference_complex_ids: Optional[list[str]] = None,
    reference_scaffold_ids: Optional[list[str]] = None,
    counterstate_source_ids: Optional[list[str]] = None,
    confirmation_strategy: Optional[str] = None,
    session_id: Optional[str] = None,
    step: int = 0,
    **_: Any,
) -> dict[str, Any]:
    mmcif = Path(target_mmcif).expanduser().resolve() if target_mmcif else None
    if mmcif is not None and (not mmcif.exists() or not mmcif.is_file()):
        return {"summary": f"Error: target mmCIF not found: {target_mmcif}", "error": "not_found", "metrics": {}}
    out_dir: Optional[Path] = None
    pdb_derived_from_mmcif = False
    if target_pdb:
        source = Path(target_pdb).expanduser().resolve()
        if not source.exists() or not source.is_file():
            return {
                "summary": f"Error: target PDB not found: {target_pdb}",
                "error": "not_found",
                "metrics": {},
            }
    elif mmcif is not None:
        out_dir = tool_output_dir("gpcr_target_prepare", session_id, step)
        source = out_dir / "source_from_mmcif.pdb"
        try:
            _mmcif_chain_to_pdb(mmcif, source, target_chain)
        except (OSError, TypeError, ValueError) as exc:
            return {
                "summary": f"Error: mmCIF-only target conversion failed: {exc}",
                "error": "invalid_args",
                "metrics": {},
            }
        pdb_derived_from_mmcif = True
    else:
        return {
            "summary": "Error: provide target_mmcif or target_pdb",
            "error": "invalid_args",
            "metrics": {},
        }

    try:
        hotspots = _parse_residues(binding_residues, field="binding_residues")
        excluded = _parse_residues(excluded_residues, field="excluded_residues")
        spans = _parse_spans(membrane_spans)
        unresolved_spans = _parse_optional_spans(unresolved_regions, field="unresolved_regions")
        modeled_spans = _parse_optional_spans(modeled_regions, field="modeled_regions")
        glycosylation = _parse_residues(glycosylation_sites, field="glycosylation_sites")
        evidence = _validate_experimental_evidence(experimental_evidence)
    except ValueError as exc:
        return {"summary": f"Error: {exc}", "error": "invalid_args", "metrics": {}}
    required_context = {
        "source_id": source_id,
        "receptor_id": receptor_id,
        "hypothesis_id": hypothesis_id,
        "structure_method": structure_method,
        "construct_context": construct_context,
        "ligand_context": ligand_context,
        "membrane_span_source": membrane_span_source,
        "confirmation_strategy": confirmation_strategy,
    }
    absent_context = sorted(key for key, value in required_context.items() if not value)
    if absent_context:
        return {
            "summary": f"Error: richer GPCR representation is missing required context: {absent_context}",
            "error": "invalid_args",
            "metrics": {},
        }
    if structure_method not in {"xray", "cryo_em", "nmr", "predicted", "hybrid"}:
        return {"summary": "Error: unsupported structure_method", "error": "invalid_args", "metrics": {}}
    if confirmation_strategy not in {
        "structure_conditioned",
        "state_specific_construct",
        "sequence_only_state_uncontrolled",
    }:
        return {"summary": "Error: unsupported confirmation_strategy", "error": "invalid_args", "metrics": {}}
    if not 2 <= len(hotspots) <= 12:
        return {
            "summary": "Error: binding_residues must contain 2-12 distinct residues",
            "error": "invalid_args",
            "metrics": {},
        }
    if not 2 <= len(excluded) <= 32:
        return {
            "summary": "Error: excluded_residues must contain 2-32 distinct residues",
            "error": "invalid_args",
            "metrics": {},
        }
    overlap = sorted(set(hotspots) & set(excluded))
    if overlap:
        return {
            "summary": f"Error: binding and excluded residues overlap: {overlap}",
            "error": "invalid_args",
            "metrics": {},
        }
    membrane_core = {
        residue
        for start, end in spans
        for residue in range(start, end + 1)
    }
    membrane_overlap = sorted(set(hotspots) & membrane_core)
    if membrane_overlap:
        return {
            "summary": f"Error: binding anchors fall inside membrane-core spans: {membrane_overlap}",
            "error": "invalid_args",
            "metrics": {},
        }

    text = source.read_text(encoding="utf-8", errors="replace")
    present = _present_residues(text, target_chain)
    if not present:
        return {
            "summary": f"Error: target chain {target_chain!r} has no protein atoms",
            "error": "invalid_args",
            "metrics": {},
        }
    missing = sorted((set(hotspots) | set(excluded)) - present)
    if missing:
        return {
            "summary": f"Error: requested residues absent from chain {target_chain}: {missing}",
            "error": "invalid_args",
            "metrics": {},
        }
    unresolved = _span_residues(unresolved_spans)
    modeled = _span_residues(modeled_spans)
    inconsistent_unresolved = sorted(unresolved & present)
    if inconsistent_unresolved:
        return {
            "summary": f"Error: unresolved_regions contain residues with coordinates: {inconsistent_unresolved}",
            "error": "invalid_args",
            "metrics": {},
        }
    absent_modeled = sorted(modeled - present)
    if absent_modeled:
        return {
            "summary": f"Error: modeled_regions contain residues without coordinates: {absent_modeled}",
            "error": "invalid_args",
            "metrics": {},
        }
    uncertain_hotspots = sorted(set(hotspots) & (unresolved | modeled))
    if uncertain_hotspots:
        return {
            "summary": f"Error: binding anchors cannot rely on unresolved or modeled residues: {uncertain_hotspots}",
            "error": "invalid_args",
            "metrics": {},
        }
    try:
        markers = _validate_state_markers(state_markers, present, receptor_state)
        reference_complexes = _normalized_ids(reference_complex_ids, field="reference_complex_ids")
        reference_scaffolds = _normalized_ids(reference_scaffold_ids, field="reference_scaffold_ids")
        counterstates = _normalized_ids(counterstate_source_ids, field="counterstate_source_ids")
        verified_portfolio_path = _verify_portfolio_link(
            hypothesis_portfolio_path,
            hypothesis_id=str(hypothesis_id),
            receptor_id=str(receptor_id),
            receptor_state=receptor_state,
            binding_side=binding_side,
            hotspots=hotspots,
            excluded=excluded,
        )
    except ValueError as exc:
        return {"summary": f"Error: {exc}", "error": "invalid_args", "metrics": {}}
    if structure_method in {"xray", "cryo_em"} and structure_resolution_angstrom is None:
        return {
            "summary": f"Error: structure_resolution_angstrom is required for {structure_method}",
            "error": "invalid_args",
            "metrics": {},
        }
    try:
        topology = _face_topology(
            text,
            target_chain,
            spans,
            hotspots,
            excluded,
            binding_side,
        )
    except ValueError as exc:
        return {"summary": f"Error: GPCR topology validation failed: {exc}", "error": "invalid_args", "metrics": {}}

    prepared_text, _, _ = _filter_pdb(text, chain=target_chain, crop=None)
    n_atoms = sum(
        1
        for line in prepared_text.splitlines()
        if line.startswith("ATOM  ") and _line_chain(line) == target_chain
    )
    n_residues = len(present)
    if out_dir is None:
        out_dir = tool_output_dir("gpcr_target_prepare", session_id, step)
    prepared_path = out_dir / "prepared_gpcr.pdb"
    prepared_path.write_text(prepared_text, encoding="utf-8")
    source_copy = out_dir / "source.pdb"
    if source_copy != source:
        shutil.copy2(source, source_copy)

    mapping_verified = False
    label_chain: Optional[str] = None
    label_hotspots: list[int] = []
    label_excluded: list[int] = []
    label_state_markers: list[dict[str, Any]] = []
    prepared_mmcif_path: Optional[Path] = None
    numbering_map_path: Optional[Path] = None
    if mmcif is not None:
        try:
            label_chain, numbering = _mmcif_numbering(mmcif, target_chain)
            absent = sorted((set(hotspots) | set(excluded)) - numbering.keys())
            if absent:
                raise ValueError(f"requested author residues absent from mmCIF mapping: {absent}")
            label_hotspots = [numbering[value] for value in hotspots]
            label_excluded = [numbering[value] for value in excluded]
            label_state_markers = [
                {
                    **marker,
                    "residues_label": [numbering[value] for value in marker["residues_author"]],
                }
                for marker in markers
            ]
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return {"summary": f"Error: canonical mmCIF mapping failed: {exc}", "error": "invalid_args", "metrics": {}}
        prepared_mmcif_path = out_dir / "prepared_gpcr.cif"
        shutil.copy2(mmcif, prepared_mmcif_path)
        numbering_map_path = out_dir / "residue_numbering_map.json"
        numbering_map_path.write_text(
            json.dumps(
                {
                    "auth_chain": target_chain,
                    "label_chain": label_chain,
                    "author_to_label": {str(key): value for key, value in sorted(numbering.items())},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        mapping_verified = True

    nonprotein_context = sorted(
        {
            f"{line[17:20].strip()}:{_line_resi(line)}"
            for line in text.splitlines()
            if line.startswith("HETATM")
            and _line_chain(line) == target_chain
            and line[17:20].strip() not in {"HOH", "WAT"}
        }
    )
    representation_warnings: list[str] = []
    if confirmation_strategy == "sequence_only_state_uncontrolled":
        representation_warnings.append(
            "Sequence-only confirmation does not preserve or test the selected receptor conformation."
        )
    if not counterstates:
        representation_warnings.append("No counterstate structure was declared for ensemble discrimination.")
    if not reference_complexes:
        representation_warnings.append("No experimental reference complex was declared for interface calibration.")
    if not reference_scaffolds:
        representation_warnings.append("No experimentally observed VHH scaffold was declared.")
    absent_glycosylation = sorted(set(glycosylation) - present)
    direct_evidence_count = sum(item["directness"] == "direct_same_receptor" for item in evidence)
    hypothesis_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "receptor_id": receptor_id,
                "state": receptor_state,
                "side": binding_side,
                "anchors": hotspots,
                "exclusions": excluded,
                "source": source_id,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]

    manifest = {
        "schema_version": 3,
        "source_id": source_id,
        "receptor_id": receptor_id,
        "hypothesis_id": hypothesis_id,
        "hypothesis_fingerprint": hypothesis_fingerprint,
        "hypothesis_portfolio_path": verified_portfolio_path,
        "coordinate_source_format": "mmcif_only" if pdb_derived_from_mmcif else "pdb_with_mmcif",
        "pdb_derived_from_mmcif": pdb_derived_from_mmcif,
        "source_pdb_path": str(source_copy),
        "prepared_pdb_path": str(prepared_path),
        "prepared_mmcif_path": str(prepared_mmcif_path) if prepared_mmcif_path else None,
        "numbering_map_path": str(numbering_map_path) if numbering_map_path else None,
        "target_chain": target_chain,
        "target_auth_chain": target_chain,
        "target_label_chain": label_chain,
        "binding_side": binding_side,
        "receptor_state": receptor_state,
        "binding_residues": hotspots,
        "excluded_residues": excluded,
        "binding_residues_author": hotspots,
        "excluded_residues_author": excluded,
        "binding_residues_label": label_hotspots,
        "excluded_residues_label": label_excluded,
        "membrane_spans_author": [[start, end] for start, end in spans],
        "membrane_span_source": str(membrane_span_source).strip(),
        "mapping_verified": mapping_verified,
        "topology_verified": True,
        "topology_geometry": topology,
        "epitope_rationale": epitope_rationale.strip(),
        "state_rationale": state_rationale.strip(),
        "target_representation": {
            "structure_method": structure_method,
            "structure_resolution_angstrom": structure_resolution_angstrom,
            "coordinate_source_format": "mmcif_only" if pdb_derived_from_mmcif else "pdb_with_mmcif",
            "construct_context": str(construct_context).strip(),
            "ligand_context": str(ligand_context).strip(),
            "nonprotein_entities_on_target_chain": nonprotein_context,
            "unresolved_regions_author": [[start, end] for start, end in unresolved_spans],
            "modeled_regions_author": [[start, end] for start, end in modeled_spans],
            "glycosylation_sites_author": glycosylation,
            "glycosylation_sites_without_coordinates": absent_glycosylation,
            "state_markers": label_state_markers if mapping_verified else markers,
            "reference_complex_ids": reference_complexes,
            "reference_scaffold_ids": reference_scaffolds,
            "counterstate_source_ids": counterstates,
            "confirmation_strategy": confirmation_strategy,
            "confirmation_state_preserved": confirmation_strategy != "sequence_only_state_uncontrolled",
            "warnings": representation_warnings,
        },
        "experimental_evidence": evidence,
        "direct_same_receptor_evidence_count": direct_evidence_count,
        "experimentally_grounded": True,
        "num_residues": n_residues,
        "num_atoms": n_atoms,
        "full_chain_preserved": True,
    }
    manifest_path = out_dir / "target_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "summary": (
            f"Prepared intact {receptor_state} GPCR chain {target_chain} for {binding_side} design: "
            f"{n_residues} residues, {len(hotspots)} epitope anchors, "
            f"canonical mapping {'verified' if mapping_verified else 'missing'}, "
            f"coordinates {'converted from mmCIF' if pdb_derived_from_mmcif else 'read from PDB'}, "
            f"{len(evidence)} experimental evidence records, "
            f"{len(representation_warnings)} representation warnings"
        ),
        "target_manifest_path": str(manifest_path),
        **manifest,
        "metrics": {
            "num_residues": n_residues,
            "num_binding_residues": len(hotspots),
            "num_experimental_evidence": len(evidence),
            "num_direct_same_receptor_evidence": direct_evidence_count,
            "num_representation_warnings": len(representation_warnings),
            "pdb_derived_from_mmcif": pdb_derived_from_mmcif,
        },
        "session_id": session_id,
    }


__all__ = ["gpcr_hypothesis_portfolio", "gpcr_target_prepare"]
