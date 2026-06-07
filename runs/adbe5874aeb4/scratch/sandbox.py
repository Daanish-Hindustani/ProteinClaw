"""Structural sandbox on TREM2 5ELI chain A crop 20-131."""
from Bio.PDB import PDBParser
from Bio.PDB.SASA import ShrakeRupley

PDB = "/home/ubuntu/.proteinclaw/gpu-workspace/adbe5874aeb4/pdb_fetch_0/5ELI_chainA_crop20-131.pdb"
HYDRO = set("ALA VAL LEU ILE MET PHE TRP TYR PRO".split())
AA3to1 = {"ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLU":"E","GLN":"Q","GLY":"G",
          "HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P","SER":"S",
          "THR":"T","TRP":"W","TYR":"Y","VAL":"V"}

parser = PDBParser(QUIET=True)
s = parser.get_structure("trem2", PDB)
sr = ShrakeRupley(probe_radius=1.4, n_points=100)
sr.compute(s, level="R")

residues = []
for res in s[0]["A"].get_residues():
    if res.id[0] != " ":  # HETATM
        continue
    aa3 = res.get_resname()
    aa1 = AA3to1.get(aa3, "X")
    sasa = res.sasa
    residues.append((res.id[1], aa3, aa1, sasa))

# Print exposed (sasa > 40) residues
print("EXPOSED (sasa>40):")
for num, aa3, aa1, sasa in residues:
    if sasa > 40:
        tag = "[HYDRO]" if aa3 in HYDRO else "[BASIC]" if aa3 in {"ARG","LYS","HIS"} else ""
        print(f"  {aa1}{num:3d} {aa3} sasa={sasa:5.1f} {tag}")

# Print apex / CDR-like loop residues (known TREM2 binding site)
print("\nApex / CDR-like loops (literature-canonical):")
apex_ids = [42,43,44,45,46,47,48,49,50,66,67,68,69,70,71,72,73,74,75,76,77,78,
            96,97,98,99,100,101,102,103]
by_num = {r[0]: r for r in residues}
for n in apex_ids:
    if n in by_num:
        num, aa3, aa1, sasa = by_num[n]
        tag = "[HYDRO]" if aa3 in HYDRO else "[BASIC]" if aa3 in {"ARG","LYS","HIS"} else ""
        print(f"  {aa1}{num:3d} {aa3} sasa={sasa:5.1f} {tag}")
