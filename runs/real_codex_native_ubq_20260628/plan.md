

## Native Research Record

{
  "type": "research_record",
  "source": "codex_native_web",
  "query": "RFdiffusion binder design ubiquitin 1UBQ ProteinMPNN AlphaFold2 multimer",
  "summary": "Native Codex web research found RFdiffusion supports de-novo binder backbone generation from target/hotspot specifications, ProteinMPNN sequence design plus AF2/AF2-multimer screening is a standard downstream filter, and RCSB 1UBQ is a compact monomeric 76-residue ubiquitin structure suitable for a fast live target.",
  "citations": [
    {
      "title": "De novo design of protein structure and function with RFdiffusion",
      "url": "https://www.nature.com/articles/s41586-023-06415-8"
    },
    {
      "title": "RCSB PDB 1UBQ",
      "url": "https://www.rcsb.org/structure/1UBQ"
    },
    {
      "title": "Improving de novo protein binder design with deep learning",
      "url": "https://www.nature.com/articles/s41467-023-38328-5"
    }
  ],
  "notes": "User requested proof that native web was used; this record captures the host-agent web search result, not a ProteinClaw MCP web wrapper.",
  "ts": 1782614039.373616
}


## Native Debate Record

{
  "type": "debate_record",
  "subagent_type": "codex_native_subagent",
  "prompt": "Critique ubiquitin 1UBQ minibinder run plan with RFdiffusion3, ProteinMPNN, ESMFold, AF2-multimer, interface metrics.",
  "position": "Initial plan used dispersed hotspots A8,A44,A68; subagent challenged this as geometrically weak.",
  "summary": "Native subagent recommended keeping 1UBQ chain A crop 1-76 but changing to a compact hotspot patch around A44,A68,A70, sampling a 35-55 aa binder range, and enforcing strict downstream interface metrics because ubiquitin is compact and shallow.",
  "evidence": [
    "Hotspots should define a coherent epitope for RFdiffusion-style conditioning.",
    "Ubiquitin is small and compact, so false positives from shallow contacts are plausible.",
    "Proceed with compact hotspots A44,A68,A70 rather than changing target."
  ],
  "decision": "Adopt compact hotspots A44,A68,A70 and binder_length 35-55 for this run.",
  "ts": 1782614039.376263
}


## Round 1 Design Hypothesis

Target: RCSB 1UBQ ubiquitin, chain A, residues 1-76. Native web supports RFdiffusion-style hotspot-conditioned binder generation followed by ProteinMPNN sequence design and AF2/AF2-multimer filtering. Native subagent critique rejected dispersed hotspots A8,A44,A68 and recommended a compact patch around A44,A68,A70. Execute a bounded but real candidate round: RFD3 num_designs=4, timesteps=100, binder_length=35-55; ProteinMPNN two sequences per backbone; ESMFold screen all sequences; AF2-multimer with ColabFold MSA on the top ESMFold sequence; score interface metrics with hotspots A44,A68,A70.


## Round 1 ESMFold Selection

Selected top ESMFold sequence MEVIPPVT... length 37 with pLDDT 80.62.
