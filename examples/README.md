# examples/

Reference outputs from real `proteinclaw run` invocations. Used as
fixtures for documentation, UI screenshots, and onboarding.

## Runs

| Run | Target | What it shows |
|---|---|---|
| [`runs/pdl1-binder-colabfold/`](./runs/pdl1-binder-colabfold/) | PD-L1 IgV (PDB 6NM7) | Full 8-step pipeline with `msa_source=colabfold` — produces 4 ranked binders with the rank-1 design at complex pLDDT 79.65 (borderline literature hit-gate). |

Each run directory contains:
- `README.md` — what the run did, summary stats, how to reproduce
- `result.json` — machine-readable run record
- `report.html` — self-contained interactive UI
- `trace.jsonl` — full agent event log
- `designs/rank_NN_<id>.pdb` — top-K AF2-multimer complex PDBs

These are checked into the repo as fixtures, NOT as canonical "good
designs" — proteinclaw is a research tool, and any binder needs wet-lab
validation. The reports are useful for:
- Understanding what the agent's output looks like before installing.
- Smoke-testing changes to `report.py` against a real triage result.
- Snapshot-testing the schema of `result.json`.
