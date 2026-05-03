---
name: pubmed-search
description: Use pubmed_search for biomedical literature discovery with query expansion, abstract review, and PMID/DOI-grounded citations.
version: 1.0.0
author: ProteinClaw
license: MIT
metadata:
  hermes:
    tags: [protein-design, pubmed, literature, papers]
    related_skills: [uniprot-search, rcsb-search]
---

# PubMed Search

Use `pubmed_search` when the user asks for biomedical papers, mechanisms,
benchmarks, biological precedent, protein-design literature, or evidence for a
target/design strategy.

## Workflow

1. Start with a review-oriented query when entering a field.
2. Run `pubmed_search` with the user's query; the tool automatically expands it
   into multiple query variants and deduplicates by PMID/DOI.
3. Prefer papers with abstracts, clear methods, and direct relevance to the
   target protein, family, ligand, interface, enzyme mechanism, or design method.
4. Cite PMID and DOI when available.
5. Be blunt about weak evidence: computational predictions, preclinical assays,
   and wet-lab validation are different levels of support.

## Query Guidance

Good queries include the biological entity and the action:

- `KRAS G12D binder protein design`
- `PD-L1 protein protein interaction interface structure`
- `cysteine hydrolase enzyme design catalytic triad`

When results are noisy, narrow by organism, domain name, ligand, disease area,
or method name.

## Output Guidance

Summaries should include:

- What the paper shows
- Why it matters for the design task
- PMID/DOI
- Any caveat that affects downstream design
