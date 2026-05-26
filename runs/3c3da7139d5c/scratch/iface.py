"""Characterize the ubiquitin surface: relative SASA per residue, identify
exposed hydrophobic patches (esp. the Ile44 patch), pick hotspot atoms."""
from Bio.PDB import PDBParser
from Bio.PDB.SASA import ShrakeRupley
from Bio.PDB.Polypeptide import is_aa

PDB = "/home/ubuntu/.proteinclaw/gpu-workspace/3c3da7139d5c/pdb_fetch_0/1UBQ_chainA_crop1-76.pdb"

# Tien et al. 2013 theoretical max ASA (Gly-X-Gly)
MAXASA = {"ALA":129,"ARG":274,"ASN":195,"ASP":193,"CYS":167,"GLN":225,"GLU":223,
          "GLY":104,"HIS":224,"ILE":197,"LEU":201,"LYS":236,"MET":224,"PHE":240,
          "PRO":159,"SER":155,"THR":172,"TRP":285,"TYR":263,"VAL":174}
HYDROPHOBIC = {"ALA","VAL","LEU","ILE","MET","PHE","TRP","PRO","CYS"}

p = PDBParser(QUIET=True)
s = p.get_structure("ub", PDB)
model = s[0]
sr = ShrakeRupley()
sr.compute(model, level="R")

rows = []
for res in model["A"]:
    if not is_aa(res, standard=True):
        continue
    rn = res.resname
    rsasa = res.sasa / MAXASA[rn] if rn in MAXASA else 0
    rows.append((res.id[1], rn, res.sasa, rsasa))

print("Exposed residues (relSASA > 0.30):")
for num, rn, sasa, rel in rows:
    if rel > 0.30:
        tag = " <-- HYDROPHOBIC" if rn in HYDROPHOBIC else ""
        print(f"  {rn}{num:>3}  SASA={sasa:6.1f}  rel={rel:.2f}{tag}")

print("\nIle44 patch members (classic UBD recognition surface):")
patch = {8:"LEU",44:"ILE",68:"HIS",70:"VAL",47:"GLY",36:"ILE",4:"PHE"}
for num, rn, sasa, rel in rows:
    if num in patch:
        print(f"  {rn}{num:>3}  SASA={sasa:6.1f}  rel={rel:.2f}")
