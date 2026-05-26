"""Surface exposure + spatial clustering of candidate TREM2 epitopes on 5ELI chain A crop.
Uses biopython Shrake-Rupley SASA (no freesasa needed)."""
import sys
import numpy as np
from Bio.PDB import PDBParser, Selection
from Bio.PDB.SASA import ShrakeRupley

PDB = "/home/ubuntu/.proteinclaw/gpu-workspace/6e8c60a78622/pdb_fetch_0/5ELI_chainA_crop20-131.pdb"

# Max ASA (Tien 2013 theoretical) for relative SASA
MAXASA = {"A":129,"R":274,"N":195,"D":193,"C":167,"E":223,"Q":225,"G":104,
          "H":224,"I":197,"L":201,"K":236,"M":224,"F":240,"P":159,"S":155,
          "T":172,"W":285,"Y":263,"V":174}
THREE2ONE = {"ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLU":"E","GLN":"Q",
             "GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F",
             "PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V"}
HYDROPHOBIC = set("AVILMFWYC")

p = PDBParser(QUIET=True)
s = p.get_structure("trem2", PDB)
ShrakeRupley().compute(s, level="R")
chain = list(s.get_chains())[0]

res_info = {}
for res in chain:
    if res.id[0] != " ":
        continue
    aa = THREE2ONE.get(res.resname)
    if aa is None:
        continue
    rn = res.id[1]
    rsa = res.sasa / MAXASA[aa]
    # CB coord (CA for gly)
    atom = res["CB"] if "CB" in res else res["CA"]
    res_info[rn] = {"aa": aa, "rsa": round(rsa, 2), "sasa": round(res.sasa,1),
                    "coord": atom.coord, "hphob": aa in HYDROPHOBIC}

# Candidate epitopes from scouts
DISTAL = [23, 102, 107, 125, 127, 128, 130]      # scout 1 distal beta-sandwich hydrophobic face
BASIC  = [47, 62, 69, 70, 76, 77]                 # scout 2 apical CDR / basic patch

def report(name, resids):
    print(f"\n=== {name} ===")
    coords = []
    for rn in resids:
        info = res_info.get(rn)
        if info is None:
            print(f"  res {rn}: NOT in crop/modeled")
            continue
        exp = "EXPOSED" if info["rsa"] >= 0.25 else "buried "
        print(f"  {info['aa']}{rn}: RSA={info['rsa']:.2f} {exp} {'hphob' if info['hphob'] else 'polar'}")
        if info["rsa"] >= 0.20:
            coords.append(info["coord"])
    if len(coords) >= 2:
        coords = np.array(coords)
        cen = coords.mean(axis=0)
        spread = np.sqrt(((coords-cen)**2).sum(axis=1)).max()
        # max pairwise dist
        d = np.sqrt(((coords[:,None,:]-coords[None,:,:])**2).sum(-1))
        print(f"  -> {len(coords)} exposed residues, centroid spread (max from centroid)={spread:.1f} A, max pairwise={d.max():.1f} A")

report("DISTAL beta-sandwich hydrophobic face (scout 1)", DISTAL)
report("BASIC / apical CDR patch (scout 2)", BASIC)

# Find all exposed hydrophobic residues to spot natural patches
print("\n=== All exposed hydrophobic residues (RSA>=0.25) ===")
exp_hphob = [(rn,i) for rn,i in sorted(res_info.items()) if i["hphob"] and i["rsa"]>=0.25]
print("  " + ", ".join(f"{i['aa']}{rn}({i['rsa']:.2f})" for rn,i in exp_hphob))
