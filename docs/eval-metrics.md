# Evaluation Metrics

> Stub. Authored in Phase 3.

Per-candidate metrics scored independently (no scalar collapse — Pareto-style retention is the optimizer's job):

- pLDDT / pTM (confidence)
- RMSD (structural similarity to target)
- Clash score
- Interface SASA (binding interface quality)
- Novelty (Foldseek-based)
- Constraint satisfaction (binary per declared constraint)

Thresholds live in YAML under `config/`. The Evaluator emits a `Score`, an `EvaluationVerdict` (retry / branch / stop), and a textual `Critique` (the high-bandwidth signal Feedback Descent consumes in Phase 7).
