---
name: proteinclaw-learned-live-e2e-validation
description: Learned validation notes from the real PD-L1 end-to-end ProteinClaw campaign.
---

# Real E2E Validation

Use this skill when auditing whether a ProteinClaw campaign actually exercised the full plugin workflow.

## Learned

- A real end-to-end validation should trace skill reads, research/debate records, target fetch/analyze, RFdiffusion3, ProteinMPNN, ESMFold, AF2-multimer, interface metrics, report generation, and at least one bounded skill-evolution action.
- Minimal live campaigns may use small counts, but the report must clearly separate tool-chain validity from production binder quality. This run `real_e2e_pdl1_20260630_000128` produced RFdiffusion3=1 backbone(s), MPNN=2 sequence(s), ESMFold=2 fold(s), AF2 complex_confidence=95.22, ipSAE=0.819541, interface_contacts=43.
