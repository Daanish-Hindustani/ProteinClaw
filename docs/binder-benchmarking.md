# Binder Benchmarking

ProteinClaw benchmarks separate engineering smoke tests from scientific binder
validation. The current real-backend harness is useful for proving that the
agent can call RFdiffusion, ProteinMPNN, and a fold predictor end-to-end, but a
successful smoke run is not yet a wet-lab-grade binder claim.

## Current Benchmark Layers

- `config/benchmarks/binder_mock.yaml` is the cheap CI/dev scoreboard. It checks
  orchestration, report writing, comparison, and regression gates without GPU
  cost.
- `config/benchmarks/binder_real_smoke.yaml` is the first live-tool smoke suite.
  It should run on a GPU node and is meant to catch broken installs, bad tool
  wiring, and trace aggregation regressions.
- `config/benchmarks/binder_real_panel.yaml` is the curated target panel for
  method comparisons. It includes easy, medium, hard, hotspot-guided, and
  non-hotspot binder tasks with deterministic repeat metadata.

## Binder Metrics

Benchmark V1 records both planner verdicts and binder-specific structural
signals:

- Interface contacts: target-binder residue contacts from the generated complex.
- Interface SASA: approximate buried surface area across the target-binder
  interface.
- Clash score: inter-chain heavy-atom clashes normalized per 1000 binder atoms.
- Target-binder minimum distance: closest target-binder heavy atom distance.
- Hotspot satisfaction: fraction of requested hotspot residues contacted.
- Binder monomer confidence: confidence from the folded designed binder.
- Complex confidence: current complex-level proxy from RFdiffusion confidence,
  to be replaced or supplemented by an explicit complex predictor.

## Scientific Bar

ESMFold/single-sequence folding is acceptable for smoke tests only. It helps us
detect obvious sequence/fold failures cheaply, but it does not validate binder
interfaces because it does not model the target-binder complex with paired
context.

For serious binder benchmarking, use a complex-aware validation backend such as
ColabFold/AlphaFold-Multimer or another complex predictor. The benchmark should
then gate on complex confidence, interface geometry, clashes, hotspot
satisfaction, and repeated-run stability rather than only on monomer pLDDT.

## Suggested Commands

```powershell
uv run proteinclaw benchmark run --suite config/benchmarks/binder_real_smoke.yaml --out outputs/benchmarks/real-smoke.json
uv run proteinclaw benchmark run --suite config/benchmarks/binder_real_panel.yaml --out outputs/benchmarks/real-panel.json
uv run proteinclaw benchmark compare outputs/benchmarks/baseline.json outputs/benchmarks/real-panel.json
uv run proteinclaw benchmark gate outputs/benchmarks/baseline.json outputs/benchmarks/real-panel.json --min-success-rate-delta -0.05 --max-verdict-regressions 0
```
