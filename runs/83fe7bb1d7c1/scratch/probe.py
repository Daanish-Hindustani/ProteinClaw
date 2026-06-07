from Bio.PDB import PDBParser
from Bio.PDB.SASA import ShrakeRupley
from Bio.PDB.NeighborSearch import NeighborSearch
p = PDBParser(QUIET=True)
s = p.get_structure("5eli", "/home/ubuntu/.cache/proteinclaw/pdb/5ELI.pdb")
model = s[0]
chains = sorted([c.id for c in model])
print("Chains:", chains)
A = model["A"]
# residues
res = [r for r in A if r.id[0]==" "]
print(f"chain A: {len(res)} residues, range {res[0].id[1]}-{res[-1].id[1]}")
# print sequence with numbering for the crop 20-131 region
aa3to1 = {"ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E","GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V"}
print("\nResidue numbering for key positions (literature L69/W70 + learned W44/F74/R76/W78):")
for n in [44,46,47,69,70,71,74,76,78,98,113,115,123]:
    for r in res:
        if r.id[1]==n:
            print(f"  {n}: {aa3to1.get(r.resname,'?')} ({r.resname})")
            break
# SASA + interface analysis
sr = ShrakeRupley()
sr.compute(s, level="R")
print("\nSurface-exposed hydrophobics in crop 20-131 (SASA > 30 A^2):")
hp = "AFILMVWY"
exposed=[]
for r in res:
    if 20 <= r.id[1] <= 131 and aa3to1.get(r.resname,"") in hp:
        sasa = r.sasa
        if sasa and sasa > 30:
            exposed.append((r.id[1], aa3to1[r.resname], sasa))
for x in exposed:
    print(f"  {x[0]} {x[1]}  SASA={x[2]:.1f}")
