

## Native Research Record

{
  "type": "research_record",
  "source": "native_web",
  "query": "Ubiquitin 1UBQ chain A minibinder target; Ile44 hydrophobic patch vs alternate acidic/polar patch literature and structure",
  "summary": "RCSB metadata: 1UBQ is X-ray ubiquitin refined at 1.8 A, canonical 76-residue sequence MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG. ProteinClaw PDB analysis confirmed residues A8, A44, A68, A70, A72, A73, A62, A63 are present in chain A. Literature metadata retrieved from PubMed: Komander & Rape 2012 'The ubiquitin code' (Annu Rev Biochem, DOI 10.1146/annurev-biochem-060310-170328); Vijay-Kumar et al. 1987 'Structure of ubiquitin refined at 1.8 A resolution' (J Mol Biol, DOI 10.1016/0022-2836(87)90679-6); examples of UBD/ubiquitin structures using Ile44 patch include FAAP20 UBZ (PLoS One 2015, DOI 10.1371/journal.pone.0120887), FANCL E2-like fold (JBC 2015, DOI 10.1074/jbc.M115.675835), N4BP1 CoCUN (Biomolecules 2019, DOI 10.3390/biom9070284), and TYMV protease/ubiquitin recognition (JBC 2020, DOI 10.1074/jbc.RA120.014628).",
  "citations": [
    "https://www.rcsb.org/structure/1UBQ",
    "https://doi.org/10.1016/0022-2836(87)90679-6",
    "https://pubmed.ncbi.nlm.nih.gov/22524316/",
    "https://doi.org/10.1146/annurev-biochem-060310-170328",
    "https://doi.org/10.1371/journal.pone.0120887",
    "https://doi.org/10.1074/jbc.M115.675835",
    "https://doi.org/10.3390/biom9070284",
    "https://doi.org/10.1074/jbc.RA120.014628"
  ],
  "notes": "Inference for critique: Ile44/L8/V70 hotspot choice is biologically validated but designability-challenging for a 60-75 aa de novo helical minibinder because the patch is small, shallow, hydrophobic, and re-used by many natural UBDs. Alternative polar/acidic surfaces may give stronger geometric/electrostatic specificity but should not be called more biologically canonical unless linked to a functional ubiquitin-recognition mode.",
  "ts": 1782616349.4790409
}


## Native Debate Record

{
  "type": "debate_record",
  "subagent_type": "native_subagent",
  "prompt": "Critique a plan to design a 60-75 aa helical de novo minibinder to ubiquitin PDB 1UBQ chain A using sparse hydrophobic/Ile44-patch hotspots; assess structural/designability risks, hotspot choice risks, and whether alternate acidic/polar patch is more defensible.",
  "position": "",
  "summary": "Adjudication: The Ile44 patch is defensible as a biological targeting hypothesis but risky as a sparse-hotspot de novo minibinder specification. For a 60-75 aa helical binder, sparse hydrophobic hotspots can produce underspecified, low-shape-complementarity interfaces, degenerate hydrophobic docking, and accidental mimicry of common UBD binding modes. A more polar/acidic patch is not automatically better biologically, but may be more defensible for computational design if it supplies a larger contiguous epitope, directional H-bonds/salt bridges, and negative controls against generic hydrophobic burial. Best compromise: retain I44/L8/V70 only as an anchor and add explicit polar/geometric constraints to neighboring residues, or run a parallel alternative epitope design and rank by buried area, unsatisfied polar atoms, orientation specificity, and off-target hydrophobicity.",
  "evidence": [
    "1UBQ is a 1.8 A X-ray ubiquitin structure with canonical 76 aa ubiquitin sequence.",
    "ProteinClaw analysis confirmed proposed residues A8, A44, A68, A70, A72, A73, A62, A63 are present.",
    "The ubiquitin code literature identifies ubiquitin recognition as surface- and linkage-context dependent; many UBD structures reuse the Ile44-centered hydrophobic patch.",
    "Examples from PubMed metadata show diverse natural binders involving Ile44-patch recognition, supporting biological relevance but also indicating competition/degeneracy risk."
  ],
  "decision": "Do not use a sparse hydrophobic/Ile44-only hotspot set as the sole design constraint. Use either a mixed epitope centered on I44 plus directional polar residues, or compare against an alternate polar/acidic epitope with explicit geometric constraints.",
  "ts": 1782616362.846363
}
