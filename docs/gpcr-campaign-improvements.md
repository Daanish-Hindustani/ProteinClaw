# Improving GPCR nanobody campaigns

ProteinClaw is intentionally a hypothesis-driven funnel: a small number of
designs are generated, then independently checked. The following controls make
the funnel more reliable without turning it into a large library screen.

## Recommended evidence funnel

1. **Target ensemble.** Resolve the exact receptor construct and numbering from
   UniProt/RCSB. Stage at least one active and one inactive structure (or an
   AlphaFold model with the unresolved loops marked). Keep the membrane span,
   glycosylation sites, and unresolved residues in the manifest.
2. **Competing hypotheses.** Write an extracellular/ECL and an
   intracellular/effector-face hypothesis. Each must include mapped positive
   anchors and opposite-face exclusions, plus a falsifiable prediction. Use
   `data.gpcr_hypothesis_portfolio` to reject duplicates and require structured
   experimental evidence, counterstate/reference structures, observed scaffold
   priors, and a matched control before GPU execution.
3. **Bounded generation.** Explore 3–6 hypotheses with 2–6 BoltzGen designs each.
   Only hypotheses that separate from their controls earn an 8–16-design depth
   round. Cluster by CDR sequence/pose and carry at most 4–8 diverse candidates
   forward; never increase the count to compensate for a weak structural
   hypothesis.
4. **Orthogonal checks.** Apply manifest-aware GPCR structural-triage QC, then
   AF2-multimer and five-model AF-M rescoring with at least one same-run
   decoy/negative control. Final promotion uses
   `analysis.gpcr_confirmation_gate`: absolute interface confidence plus
   across-model contact/score reproducibility and explicit separation from the
   control. Compare ipTM/ipSAE, PAE, CDR contact fraction, hotspot mapping and
   coverage, reference-calibrated BSA/clashes, and membrane penetration. A
   geometry pass or model score alone is not a binding claim.
   Sequence-only AF2/AF-M does not retain the selected active/inactive receptor
   conformation and cannot establish state selectivity; require a
   structure-conditioned or genuinely state-specific confirmation path.
5. **Liability and specificity.** Before ranking finalists, check aggregation,
   exposed hydrophobics, unusual charge, cysteine/disulfide validity,
   protease-sensitive motifs, and contacts against a small off-target GPCR
   panel. These checks should reject liabilities, not create more designs.
6. **Iterate one variable.** Research and debate again after every round. Change
   one variable (state, epitope, scaffold, or model) and record Worked/Why/Gap/
   Next in `plan.md`. Two or three weak rounds are a checkpoint for synthesis and
   a hypothesis pivot, not an automatic campaign stop.

## Experimentally grounded scaffold redesign

Do not make a generic scaffold rediscover a solved, unusual binding mechanism.
For a known VHH family such as active-state MOR Nb39/Nb62 or extracellular NbE,
use `design.boltzgen_nanobody` with `design_mode="scaffold_redesign"` and an
exact PDB/mmCIF scaffold plus BoltzGen scaffold YAML. Declare the experimental
scaffold ID in the schema-v3 target manifest. The YAML is the mutation contract:
only its `design` residue ranges are mutable, so fixed framework contacts and
validated motifs remain fixed. The wrapper requires workspace-contained files,
one included chain, explicit design ranges, appropriate structure visibility,
matching filenames, coordinate atom records, and manifest-linked provenance;
it stages the inputs and records hashes.

Use `design_mode="de_novo"` only for a genuinely new scaffold/pose hypothesis.
Start either mode with four designs during portfolio exploration. A branch earns
an 8–16 design deep dive only after known-positive recovery, matched-control
separation, and strict structural QC.

When the exact binding pose is already solved and untemplated prediction fails
to recover it, use `structure.gpcr_pose_refine`: align homologous transmembrane
C-alpha atoms by author numbering, transfer the observed VHH pose onto the
verified receptor state, graft only experimentally supported mutations, and
perform backbone-restrained OpenMM side-chain relaxation. Run candidate QC with
`target_numbering="manifest_author"`. Do not relax geometry gates merely
because a confidence model ranks the sequence highly.

## Calibration and reproducibility

Use a solved complex on the same receptor face to calibrate BSA and contact
thresholds where possible. Structural triage defaults to a clash score at most
5.0, interface and CDR3 confidence at least 0.70, and at least 90% hotspot
mapping; the reference complex can tighten BSA and clash bounds further. This
specifically prevents a large BSA and high hotspot fraction from masking a
low-confidence or interpenetrating pose. Preserve random seeds, model/container versions,
input manifests, and negative controls in the run directory. Repeat the final
2–4 candidates with an independent model or seed; report disagreement as
uncertainty. Predicted affinity is advisory and must never be presented as an
experimental Kd.

For state-dependent interfaces, calibrate confirmation on an exact known
positive before screening candidates. Sequence-only AF-M is not a valid
fail-closed gate when it cannot recover that control. Use state-conditioned
Boltz-2 with the verified receptor template, unforced pocket conditioning, and
physical-quality potentials; keep candidate and control settings identical and
require deterministic intended-face QC on every predicted sample. Boltz-2
renumbers its resolved target sequence from one; call GPCR candidate QC with
`target_numbering="prediction_sequence"` so intended and forbidden author
residues are translated through the prepared receptor rather than compared to
incompatible label numbers. For state-selective claims, run five samples on a
matched counterstate manifest and require complete distributional separation,
not only a best-model margin.

## GPU host preflight

On a reset VM, install a driver matching the CUDA image, Docker Engine, and
NVIDIA Container Toolkit before starting a campaign. Verify with:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

Run the non-GPU test suite first, then one minimal BoltzGen smoke round. Record
driver/toolkit/image versions in the campaign plan so failures are attributable
to infrastructure rather than model quality.
