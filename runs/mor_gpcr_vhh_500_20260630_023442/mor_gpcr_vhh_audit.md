# MOR GPCR VHH Candidate Workflow

Run: `mor_gpcr_vhh_500_20260630_023442`

Target: μ-opioid receptor / MOR / OPRM1.

Library: 500 generated VHHs.

AF2 target crop length: 177 aa. Crop start: 95. Hotspots: `A125,A147,A153`.

ESMFold predictions: 500.

AF2-multimer scored: 10 top ESMFold survivors.

Nanobody gate hits: 0.

Important limitation: this started the requested 500-library campaign. AF2-multimer scoring all 500 is not practical as an interactive single turn on one GPU. Continue by scoring additional ESMFold survivors in batches if the first set does not produce >=3 strict hits.
