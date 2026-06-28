---
name: proteinclaw-tool-nanobody-library
description: ProteinClaw workflow and tool guidance seeded from the repository.
source: /home/ubuntu/ProteinClaw/src/proteinclaw/skills/tools/nanobody_library.md
---

# Tool skill — `design.nanobody_library` (VHH library generator)

MCP name: `mcp__proteinclaw_tools__design_nanobody_library`. Plain-Python, no GPU.

## What it does

Generates a virtual nanobody (VHH) library by grafting diversified CDR1/CDR2/CDR3
loops onto a fixed humanized framework (`h-NbBCII10`, from PDB 3EAK). FR1/FR2/FR3/FR4
are constant; only the three CDR loops vary. **FR2 is never changed, so the VHH
hallmark tetrad (solubility residues) is preserved by construction** — you do not
need to manage tetrad positions yourself.

Writes two artifacts to the session workspace and returns their **paths** (never
the sequences inline):
- `library.fasta` — the nanobody sequences.
- `library.json` — per-sequence records: `{id, sequence, cdr1:[s,e], cdr2:[s,e],
  cdr3:[s,e], cdr3_seq}` (1-based inclusive ranges on the nanobody sequence).

## Parameters

- `n_designs` (default 100, max 5000): how many to generate. **Start small** —
  AF2-multimer scoring downstream is the bottleneck. A few hundred per round is
  realistic on one GPU; 10⁴ (as in the paper) is not.
- `framework` (default `h-NbBCII10`): the only framework wired today.
- `cdr3_min_len` / `cdr3_max_len` (default 9–18): CDR3 is the long, dominant
  paratope loop; widen the range to explore, narrow to focus.
- `external_fasta`: path to a user-supplied VHH FASTA to screen **instead** of
  generating. CDR ranges are left null for external sequences (no ANARCI in the
  loop), so the CDR-aware metrics degrade to null for those — acceptable.
- `seed`: optional, for reproducible generation. The `library.json` file is the
  canonical reproducibility artifact regardless.

## How it threads into the pipeline

1. Generate → `library.json` + `library.fasta`.
2. ESMFold-prefilter the monomers (`structure_esmfold`), drop misfolders.
3. AF2-multimer each survivor against the target (`structure_alphafold2_multimer`,
   `binder_sequence` = the nanobody).
4. **Pass each design's CDR ranges from `library.json` to
   `analysis_interface_metrics` as `cdr_ranges`** — this is what enables
   `interface_plddt`, `h3_plddt`, and `cdr_contact_fraction` (the nanobody gate
   needs them). Because AF2 puts the nanobody on chain A renumbered from 1, the
   `library.json` ranges map directly onto the chain-A residue numbers.

## Gotchas

- The library is purely combinatorial CDR diversification — realistic but not a
  position-specific germline model. If hit rates are poor, feed a curated/natural
  VHH library via `external_fasta` instead.
- Do not run `design_proteinmpnn` on these — the library already *is* the
  sequences; MPNN redesign is the mini-binder paradigm, not this one.
