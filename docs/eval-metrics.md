# Evaluation Metrics

Per-candidate metrics scored independently — no scalar collapse. The
optimizer keeps the multi-objective signal (Pareto-friendly).

The Evaluator (`src/proteinclaw/evaluation/evaluator.py`) emits three
artifacts per branch:

- **`Score`** — per-metric values (typed `MetricScore` records, with optional pass/fail decisions).
- **`Verdict`** — recommendation to the orchestrator: `STOP_SUCCESS`, `RETRY`, `BRANCH`, or `STOP_FAILURE`.
- **`Critique`** — textual feedback (summary + weaknesses + suggestions). High-bandwidth signal Feedback Descent will consume in Phase 7.

## Metrics

<!-- AUTO-GENERATED:metrics (source: src/proteinclaw/common/types.py::Metric + config/evaluation.yaml) -->

| Metric | Wire value | Default threshold | Direction | Notes |
|---|---|---|---|---|
| `PLDDT` | `plddt` | `0.80` | `gte` | Confidence in predicted structure (0–1). |
| `PTM` | `ptm` | `0.70` | `gte` | Predicted TM-score; topology plausibility. |
| `RMSD` | `rmsd` | `3.0` | `lte` | Backbone RMSD vs. reference, in Å. |
| `CLASH_SCORE` | `clash_score` | `5.0` | `lte` | Phenix-style clash count per 1000 atoms. |
| `INTERFACE_SASA` | `interface_sasa` | `600.0` | `gte` | Buried surface area at the binder interface (Å²). |
| `NOVELTY` | `novelty` | `0.50` | `gte` | `1 − top_TM_score` from Foldseek; clamped to [0, 1]. |
| `CONSTRAINT_SATISFACTION` | `constraint_satisfaction` | `1.0` | `gte` | Binary fraction of declared constraints met. |

<!-- /AUTO-GENERATED:metrics -->

Thresholds are **defaults** — every `SuccessCriterion` on a `Task` can
override per-metric thresholds. The defaults live in `config/evaluation.yaml`;
that file is the single source of truth and is loaded at runtime by
`EvaluationConfig.from_yaml()`.

## Verdict policy

```text
all criteria pass            → STOP_SUCCESS
no criteria provided         → STOP_FAILURE
pass_fraction >= retry_floor → RETRY
pass_fraction <  retry_floor → BRANCH
```

`retry_floor` defaults to `0.50` (also in `config/evaluation.yaml`).

## Comparison directions

<!-- AUTO-GENERATED:comparisons (source: src/proteinclaw/common/types.py::Comparison) -->

| `Comparison` member | Wire value | Meaning |
|---|---|---|
| `GTE` | `gte` | observed ≥ threshold |
| `LTE` | `lte` | observed ≤ threshold |
| `EQ` | `eq` | observed == threshold |

<!-- /AUTO-GENERATED:comparisons -->

## Extractor registry

`src/proteinclaw/evaluation/metrics.py::EXTRACTORS` maps each `Metric`
to a pure extractor function over a branch payload. Phase 6 wires real
PDB-parsing computations behind the same signature; until then the
RMSD / clash / SASA / constraint extractors read pre-computed values
from `payload["metrics"][<key>]`.
