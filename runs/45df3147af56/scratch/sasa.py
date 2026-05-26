from Bio.PDB import PDBParser
from Bio.PDB.SASA import ShrakeRupley
p = PDBParser(QUIET=True)
s = p.get_structure("ubq", "/home/ubuntu/.proteinclaw/gpu-workspace/45df3147af56/pdb_fetch_0/1UBQ_chainA_crop1-76.pdb")
ShrakeRupley().compute(s, level="R")
patch = {8:"LEU",44:"ILE",70:"VAL",68:"HIS",42:"ARG",4:"PHE"}
ch = s[0]["A"]
for r in ch:
    rid = r.id[1]
    if rid in patch:
        print(f"{r.resname}{rid}  SASA={r.sasa:6.1f} A^2")
