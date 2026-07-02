"""``design.nanobody_library`` — generate a virtual VHH (nanobody) library.

Replicates the *library + AlphaFold-Multimer scoring* paradigm (Harvey/Smith
et al., bioRxiv 2025.03.05.640882): instead of diffusing backbones, we graft
diversified CDR loops onto a **fixed humanized VHH framework** and let
AF2-multimer + the nanobody hit gate do the selecting downstream.

Framework: ``h-NbBCII10`` (the humanized universal nanobody scaffold derived
from cAbBCII10; sequence taken from PDB 3EAK, His-tag stripped). The framework
is split into FR1/FR2/FR3/FR4 constant regions plus the three native CDRs; the
generator replaces only CDR1/CDR2/CDR3. **FR2 is held constant**, so the
hallmark VHH *tetrad* (the four FR2 solubility residues) is preserved by
construction — no explicit position arithmetic needed.

This is a plain-Python (no GPU) tool: it writes ``library.fasta`` +
``library.json`` (per-sequence CDR residue ranges, 1-based inclusive) to the
session workspace and returns **paths**, never sequences-through-context. The
emitted CDR ranges flow downstream into the CDR-aware interface metrics
(``cdr_contact_fraction``, ``h3_plddt``) — we know them exactly because we
placed them, so ANARCI/IMGT numbering is not needed in the core loop.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Optional

from proteinclaw.tools import registry
from proteinclaw.tools._paths import tool_output_dir

# --- frameworks -------------------------------------------------------------
# h-NbBCII10 (humanized NbBCII10-FGLA), PDB 3EAK chain A, His-tag + linker
# (``RGRHHHHHH``) stripped. Partitioned into 4 constant framework regions plus
# the 3 native CDRs; FR1+CDR1+FR2+CDR2+FR3+CDR3+FR4 reconstructs the parent
# exactly (locked by a unit test). FR2 carries the VHH hallmark tetrad and is
# never varied.
H_NBCII10 = {
    "fr1": "QVQLVESGGGLVQPGGSLRLSCAAS",
    "native_cdr1": "GGSEYSYSTFSLG",
    "fr2": "WFRQAPGQGLEAVAA",
    "native_cdr2": "IASMGGLT",
    "fr3": "YYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCAA",
    "native_cdr3": "VRGYFMRLPSSHNFRY",
    "fr4": "WGQGTLVTVSS",
}

FRAMEWORKS = {"h-NbBCII10": H_NBCII10}

# CDR amino-acid composition: VHH paratopes are enriched in Tyr/Ser/Gly plus
# polar/charged residues. Cys is excluded (avoids spurious disulfides) as is the
# oxidation-prone Met. Weights are a germline-biased approximation, not a
# position-specific matrix — see the plan's "library realism" risk.
_CDR_ALPHABET = "GASTNDQEKRHYWFLIVP"
_CDR_WEIGHTS = (
    14, 8, 10, 9, 7, 8, 5, 5, 5, 7, 3, 12, 4, 6, 5, 4, 5, 4
)  # G high, Y high, S/T/A/D/N moderate; sums need not normalize for random.choices

# Default CDR length ranges (inclusive). CDR3 is the long, dominant loop.
_CDR1_LEN = (7, 13)
_CDR2_LEN = (6, 9)
_CDR3_LEN_DEFAULT = (9, 18)

_MAX_DESIGNS = 5000

_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "n_designs": {
            "type": "integer",
            "minimum": 1,
            "maximum": _MAX_DESIGNS,
            "default": 100,
            "description": "Number of nanobody sequences to generate (ignored if external_fasta given).",
        },
        "framework": {
            "type": "string",
            "enum": ["h-NbBCII10"],
            "default": "h-NbBCII10",
            "description": "VHH framework scaffold to graft CDRs onto.",
        },
        "cdr3_min_len": {
            "type": "integer",
            "minimum": 3,
            "maximum": 30,
            "default": 9,
            "description": "Minimum CDR3 loop length.",
        },
        "cdr3_max_len": {
            "type": "integer",
            "minimum": 3,
            "maximum": 30,
            "default": 18,
            "description": "Maximum CDR3 loop length.",
        },
        "external_fasta": {
            "type": "string",
            "description": (
                "Optional path to a user-supplied FASTA of VHH sequences to use "
                "verbatim instead of generating. CDR ranges are left null for "
                "external sequences (no ANARCI numbering in the core loop)."
            ),
        },
        "seed": {
            "type": "integer",
            "description": "Optional RNG seed for reproducible generation (the library file is the canonical artifact regardless).",
        },
        "session_id": {"type": "string"},
        "step": {"type": "integer", "default": 0},
    },
    "required": [],
}


def _sample_loop(rng: random.Random, length: int) -> str:
    return "".join(rng.choices(_CDR_ALPHABET, weights=_CDR_WEIGHTS, k=length))


def _assemble(fw: dict[str, str], cdr1: str, cdr2: str, cdr3: str) -> dict[str, Any]:
    """Concatenate framework + CDRs, returning the sequence and 1-based CDR ranges."""
    parts = [fw["fr1"], cdr1, fw["fr2"], cdr2, fw["fr3"], cdr3, fw["fr4"]]
    seq = "".join(parts)
    p = len(fw["fr1"])
    cdr1_range = [p + 1, p + len(cdr1)]
    p += len(cdr1) + len(fw["fr2"])
    cdr2_range = [p + 1, p + len(cdr2)]
    p += len(cdr2) + len(fw["fr3"])
    cdr3_range = [p + 1, p + len(cdr3)]
    return {
        "sequence": seq,
        "cdr1": cdr1_range,
        "cdr2": cdr2_range,
        "cdr3": cdr3_range,
        "cdr3_seq": cdr3,
    }


def _parse_fasta(text: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    header: Optional[str] = None
    chunks: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(chunks)))
            header = line[1:].strip() or f"seq{len(records)}"
            chunks = []
        else:
            chunks.append(line)
    if header is not None:
        records.append((header, "".join(chunks)))
    return records


# Conserved VHH framework anchors for lightweight CDR numbering of *external*
# sequences (no ANARCI/HMMER dependency). These motifs are highly conserved
# across camelid VHHs; numbering is APPROXIMATE (a residue or two off at the
# fuzzy CDR2 boundary) but good enough for cdr_contact_fraction / h3_plddt, and
# degrades to None on any sequence where the anchors don't line up.
_FR2_TRP = re.compile(r"W[FYVILM][RKQGN]")       # FR2 start, e.g. WFRQ / WVRQ / WYRQ
_FR3_RF = re.compile(r"R[FY][TSAGD][ILVFMA]")    # FR3 conserved RF[TS][IL] motif
_FR4 = re.compile(r"WG[QKRPE]G")                 # FR4 start, WGQG / WGKG / WGRG


def _number_vhh_cdrs(seq: str) -> Optional[dict[str, list[int]]]:
    """Approximate CDR1/2/3 ranges (1-based inclusive) for a VHH via conserved
    framework anchors. Returns None if the sequence doesn't parse as a VHH.

    Anchors (validated against 3EAK/1MEL/1ZVH): first Cys (FR1) → CDR1 → FR2 Trp
    → CDR2 → FR3 'RF' motif → second Cys → CDR3 → FR4 'WGxG'. Offsets mirror the
    h-NbBCII10 partition used by the generator so external + generated libraries
    are numbered consistently.
    """
    c1 = seq.find("C")
    if not (10 <= c1 <= 30):
        return None
    m_fr2 = _FR2_TRP.search(seq, c1 + 1)
    if not m_fr2:
        return None
    fr2_w = m_fr2.start()
    cdr1 = (c1 + 4, fr2_w)                        # [start, end) 0-based
    cdr2_start = fr2_w + 15                       # FR2 is ~15 residues from the Trp
    m_rf = _FR3_RF.search(seq, cdr2_start)
    if not m_rf:
        return None
    cdr2 = (cdr2_start, m_rf.start() - 8)         # FR3 N-term ~8 residues before RF
    c2 = seq.find("C", m_rf.start())              # second (FR3 'YYC') Cys
    if c2 == -1:
        return None
    m_fr4 = _FR4.search(seq, c2 + 1)
    if not m_fr4:
        return None
    cdr3 = (c2 + 3, m_fr4.start())                # after 'C-x-x', up to FR4
    # Sanity: strictly increasing, non-empty loops, plausible CDR3 length.
    if not (cdr1[0] < cdr1[1] <= cdr2[0] < cdr2[1] <= c2 < cdr3[0] < cdr3[1]):
        return None
    if not (2 <= cdr1[1] - cdr1[0] <= 20 and 2 <= cdr2[1] - cdr2[0] <= 15 and 3 <= cdr3[1] - cdr3[0] <= 30):
        return None
    return {
        "cdr1": [cdr1[0] + 1, cdr1[1]],
        "cdr2": [cdr2[0] + 1, cdr2[1]],
        "cdr3": [cdr3[0] + 1, cdr3[1]],
    }


def _trim_vhh_domain(seq: str) -> str:
    """Trim a VHH sequence to the variable domain: drop anything after the FR4
    'WGxG...VTVSS' (His-tags, HA-tags, linkers) so the binder folds cleanly."""
    m = _FR4.search(seq)
    if not m:
        return seq
    # keep through the FR4 '...VTVSS' (~11 residues past the WGxG); be lenient.
    end = min(len(seq), m.start() + 12)
    # extend to a trailing 'SS' if present just past the window
    tail = seq[m.start():end + 4]
    ss = tail.rfind("SS")
    if ss != -1:
        end = m.start() + ss + 2
    return seq[:end]


@registry.register(
    name="design.nanobody_library",
    display_name="Nanobody (VHH) library generator",
    description=(
        "Generate a virtual nanobody (VHH) library by grafting diversified CDR1/2/3 "
        "loops onto a fixed humanized framework (h-NbBCII10). FR2 (the VHH hallmark "
        "tetrad) is held constant. Writes library.fasta + library.json (per-sequence "
        "CDR ranges) to the session workspace and returns paths. Use as step 2 of the "
        "nanobody-vs-GPCR workflow (library + AF-Multimer scoring); the library IS the "
        "sequences — no ProteinMPNN redesign in this paradigm."
    ),
    category="design",
    parameters=_PARAMETERS,
    usage_guide=(
        "Generate a few hundred candidates per round (AF2-multimer cost is the "
        "bottleneck), ESMFold-prefilter, then AF2-multimer each survivor against the "
        "GPCR. Pass library.json's CDR ranges to analysis.interface_metrics so "
        "cdr_contact_fraction / h3_plddt are computed. Supply external_fasta to screen "
        "a curated/natural VHH library instead of generating."
    ),
)
def nanobody_library(
    *,
    n_designs: int = 100,
    framework: str = "h-NbBCII10",
    cdr3_min_len: int = 9,
    cdr3_max_len: int = 18,
    external_fasta: Optional[str] = None,
    seed: Optional[int] = None,
    session_id: Optional[str] = None,
    step: int = 0,
    **_: Any,
) -> dict[str, Any]:
    if framework not in FRAMEWORKS:
        return {"summary": f"Error: unknown framework {framework!r}", "error": "invalid_args"}
    if cdr3_min_len > cdr3_max_len:
        return {
            "summary": f"Error: cdr3_min_len {cdr3_min_len} > cdr3_max_len {cdr3_max_len}",
            "error": "invalid_args",
        }

    out_dir = tool_output_dir("nanobody_library", session_id, step)
    records: list[dict[str, Any]] = []

    if external_fasta:
        path = Path(external_fasta)
        if not path.exists():
            return {"summary": f"Error: external_fasta not found: {external_fasta}", "error": "invalid_args"}
        n_numbered = 0
        for i, (header, raw) in enumerate(_parse_fasta(path.read_text())):
            if not raw:
                continue
            seq = _trim_vhh_domain(raw.upper())
            # Best-effort CDR numbering via framework anchors (no ANARCI). When it
            # succeeds the CDR-aware metrics + gate apply; when it fails, ranges
            # stay null and those metrics degrade to None for that design.
            cdrs = _number_vhh_cdrs(seq)
            if cdrs:
                n_numbered += 1
                cdr3_seq = seq[cdrs["cdr3"][0] - 1 : cdrs["cdr3"][1]]
            else:
                cdr3_seq = None
            records.append({
                "id": f"nb_{i:04d}",
                "header": header,
                "sequence": seq,
                "cdr1": cdrs["cdr1"] if cdrs else None,
                "cdr2": cdrs["cdr2"] if cdrs else None,
                "cdr3": cdrs["cdr3"] if cdrs else None,
                "cdr3_seq": cdr3_seq,
            })
        source = f"external_fasta ({path.name}; {n_numbered}/{len(records)} CDR-numbered)"
        if not records:
            return {"summary": f"Error: no sequences parsed from {external_fasta}", "error": "invalid_args"}
    else:
        fw = FRAMEWORKS[framework]
        rng = random.Random(seed)
        for i in range(n_designs):
            cdr1 = _sample_loop(rng, rng.randint(*_CDR1_LEN))
            cdr2 = _sample_loop(rng, rng.randint(*_CDR2_LEN))
            cdr3 = _sample_loop(rng, rng.randint(cdr3_min_len, cdr3_max_len))
            rec = _assemble(fw, cdr1, cdr2, cdr3)
            rec["id"] = f"nb_{i:04d}"
            rec["header"] = f"nb_{i:04d}|{framework}"
            records.append(rec)
        source = f"generated (framework {framework})"

    fasta_path = out_dir / "library.fasta"
    fasta_path.write_text(
        "".join(f">{r['id']}\n{r['sequence']}\n" for r in records)
    )
    json_path = out_dir / "library.json"
    json_path.write_text(json.dumps({"framework": framework, "source": source, "designs": records}, indent=2))

    lengths = [len(r["sequence"]) for r in records]
    return {
        "summary": (
            f"Nanobody library: {len(records)} sequences ({source}), "
            f"length {min(lengths)}–{max(lengths)} aa → {fasta_path}"
        ),
        "library_fasta_path": str(fasta_path),
        "library_json_path": str(json_path),
        "n_designs": len(records),
        "framework": framework,
        "metrics": {},
    }
