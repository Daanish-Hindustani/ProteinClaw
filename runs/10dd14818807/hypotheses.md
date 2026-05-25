# Design hypotheses — PD-L1 IgV de novo mini-binders (5JDS chain A)

## Round 1

### Target resolution
- **Target**: human PD-L1 (UniProt **Q9NZQ7**, 290 aa). IgV (Ig-like V-type) domain = residues 19–127.
- **Structure**: PDB **5JDS**, chain A. Chain A present runs: **18–132**, then gaps 133–200, 203–300, then 301–376.
- **Crop chosen**: **18–132** (115 aa) — covers the full IgV domain, fully gap-free (first gap starts at 133, so the skill's `18-134` example would clip the gap). Path: `gpu-workspace/10dd14818807/pdb_fetch_0/5JDS_chainA_crop18-132.pdb`.

### Scout hypotheses
- **Length/topology scout** (med-high conf): 65–80 aa **three-helix bundle** is the optimal starting topology for the flat PD-L1 CC'FG IgV β-sheet face; 60–80 aa window well-supported (Watson 2023 RFdiffusion PMID 37433327; BindCraft PMID 39677777; PD-1/PD-L1 mini-binder PMID 41278626). Caveat: a minority of hits may be mixed α/β strand-pairing binders; can't easily seed strand conditioning in the current wrapper. Falsify: <1% in-silico success for hotspot-only 60–80 aa diffusion on this target.
- **Hotspot scout**: repeatedly tripped a usage-policy false-positive (3 attempts) and returned nothing. **Substituted with my own due diligence** (below), which is target-specific and stronger.

### Due diligence (my own — §1.6)
1. **Literature** (research.literature_search): PMID **28280600** (PMC5341541, KN035/PD-L1 structure) defines the "five hotspot residues" of the PD-1/PD-L1 interface; PMID **37100904** (PMC10131520) + PMID **41278626** (PMC12633288) confirm hotspot-guided de novo PD-L1 binders are feasible (polar contacts noted as the hard part).
2. **Structural sandbox** (`scratch/iface_AB.py`, biopython contact criterion, 5.0 Å heavy-atom, chain A IgV vs chain B partner in 5JDS): top contacts =
   - **Y56 (5), D61 (5), R113 (5), Y123 (5)**, Q66 (4), **M115 (4)**, I54/V68/A121 (3), E58/E60/D73/D122 (2)…
   - This co-crystal interface (best signal, tactic #1) maps exactly onto the canonical PD-1-competitive front β-sheet face and confirms the literature set. (freesasa unavailable in venv → BSA criterion skipped; contact criterion sufficient.)

### Debate / adjudication
- Contested point: helical-only vs strand-pairing topology. **Resolution**: proceed helical (RFD3 `is_non_loopy=true` canon favors this; flat β-sheet face is amenable; wrapper lacks easy strand conditioning). Note the caveat; revisit in round 2 only if round 1 yields a "high ESM / low AF2 docks-wrong" pattern.
- Hotspot choice adjudicated on **my structural evidence** over the (absent) scout: pick the strongest co-crystal contacts that also give clean side-chain anchors.

### Chosen design hypothesis (drives §§3–8)
- **Hotspots**: `A56,A113,A115,A123` — 4 residues, sparse hint, all in crop & gap-free. Y56 (aromatic, C strand), R113 (charged, F strand), M115 (hydrophobic), Y123 (aromatic, G strand). Tight cluster on the front face = PD-1-competitive epitope. Anchor-atom intuition if supported: Y56 CG/OH, R113 CZ/NH1, M115 CG/SD, Y123 CG/OH.
- **Binder length**: `60-80` (user spec; scout-supported sweet spot).
- **Funnel** (user: "modest, ~4 backbones, validation run on 22GB"): RFD3 `num_designs=4`; MPNN `num_sequences=4` @ `sampling_temp=0.1` → 16 sequences → ESM ≥70 triage → AF2-multimer (colabfold MSA, num_models=1, num_recycle=3) on survivors. Easy-target band (co-crystal binder, clean face, no gaps) → 4 backbones validates the pipeline; ramp/partial-diffuse in round 2 only if gate unmet.
- **RFD3 params**: num_timesteps=50, step_scale=3, gamma_0=0.2, is_non_loopy=true (PPI canon).
- **Quality gate**: ≥5 designs with complex_confidence > 75 (ideally ipsae ≳ 0.3). With only 4 backbones this is ambitious; honest expectation = validate the funnel + surface best candidates.

### Budget check: round 1 of 2.
