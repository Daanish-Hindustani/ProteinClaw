---
name: proteinclaw-tool-gpcr-hypothesis-portfolio
description: Build a small, experimentally grounded portfolio of distinct GPCR nanobody hypotheses before GPU design.
---

# GPCR hypothesis portfolio

Call `data.gpcr_hypothesis_portfolio` after research fan-out and structural due
diligence, before preparing a target or spending GPU time. The portfolio turns
literature ideas into falsifiable design contracts; it does not generate an
epitope from prose.

Create 2–8 hypotheses, normally 3–6. Each hypothesis must name a specific
structure and chain, receptor state and side, author-numbered positive anchors
and exclusions, the dominant risk, one distinguishing variable, and a result
that would falsify it. Attach structured experimental evidence to every
hypothesis. At least one portfolio hypothesis must have direct same-receptor
evidence. A homolog transfer is allowed only when labelled as such.

For every hypothesis, declare:

- experimental reference complex IDs for interface/contact calibration;
- experimentally observed VHH/scaffold IDs relevant to the intended geometry;
- active, inactive, or intermediate counterstate structures;
- a matched negative control and the result that would discriminate it;
- whether confirmation is structure-conditioned, uses a state-specific
  construct, or is sequence-only and state-uncontrolled.

The tool rejects duplicate structural fingerprints even when their names
differ. It ranks exploration order by evidence strength and expected
information gain, but ranking is not promotion. Explore every hypothesis with
2–6 designs (default 4) before a deep dive. Keep the total first-wave budget
small, typically 12–24 designs across hypotheses. Only the best one or two
hypotheses may receive the 4–16-design deep-dive budget, and only after they
beat their matched controls, pass mapped GPCR QC, show a plausible membrane
approach, and repeat across independent models or seeds.

After the exploration wave, record a debate that compares failure modes by
hypothesis rather than by candidate score. Promote a hypothesis only when the
evidence suggests its structural premise worked. Otherwise change the state,
epitope, approach vector, construct, or scaffold regime and build a new
versioned portfolio. Never silently mutate the persisted portfolio manifest.

Sequence-only AF2/AF-M does not retain the input receptor conformation. It can
help rank generic complex plausibility but cannot prove active/inactive state
selectivity. A state-selective hypothesis requires a state-preserving
confirmation path or must remain explicitly unresolved.
