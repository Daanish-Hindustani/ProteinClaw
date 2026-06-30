# Live workflow smoke: live_1ubq_20260629_232800

Target: ubiquitin, PDB 1UBQ, chain A.

Purpose: verify ProteinClaw MCP workflow discipline on a live target without launching long GPU design jobs.

Skill checks:
- Read proteinclaw-workflow before tool use planning.
- Read minibinder and tool skills for RFdiffusion3, ProteinMPNN, ESMFold, AF2-multimer, and interface metrics.
- Recorded research and critique into ProteinClaw artifacts instead of using embedded subagents.

Tool checks:
- RCSB search resolved the target candidate.
- PDB fetch downloaded/cropped chain A into the run workspace.
- PDB analyze summarized chain A and checked proposed smoke-test hotspots.
- Nanobody library generated two CPU candidates only as a lightweight design-tool sanity check.

Iteration note: a real binder campaign would now loop RFdiffusion3 -> ProteinMPNN -> ESMFold/AF2-multimer -> interface metrics -> critique -> next-round parameter updates. This smoke stops before the long GPU loop.
