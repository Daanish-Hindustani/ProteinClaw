from Bio.PDB import PDBParser
from Bio.PDB.SASA import ShrakeRupley
import numpy as np
p = PDBParser(QUIET=True)
s = p.get_structure("x", "/home/ubuntu/.proteinclaw/gpu-workspace/29c9603ba01d/pdb_fetch_0/5ELI_chainA_crop20-131.pdb")
ShrakeRupley().compute(s, level="R")
A = s[0]["A"]
# Group by lateral-face VHB937 epitope bands and apical-CDR bands
lateral = list(range(20,29)) + list(range(52,60)) + list(range(102,108)) + list(range(125,132))
apical = [44,47,71,74,76,78,98]  # prior CDR loop hotspots
print("=== VHB937 lateral-face candidates (residue, name, SASA Å²) ===")
for r in A:
    rid = r.id[1]
    if rid in lateral:
        print(f"  A{rid:3d} {r.resname} SASA={r.sasa:6.1f}")
print("\n=== prior CDR ridge for comparison ===")
for r in A:
    rid = r.id[1]
    if rid in apical:
        print(f"  A{rid:3d} {r.resname} SASA={r.sasa:6.1f}")
