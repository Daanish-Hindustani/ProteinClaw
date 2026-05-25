# Identify chain B and compute PD-L1 (chain A, 18-132) interface residues vs chain B.
import json
from collections import defaultdict
from Bio.PDB import PDBParser, NeighborSearch, Selection
from Bio.PDB.Polypeptide import is_aa

_3TO1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
def three_to_one(resname):
    return _3TO1.get(resname, "X")

PDB = "/home/ubuntu/.cache/proteinclaw/pdb/5JDS.pdb"
CUT = 4.5
parser = PDBParser(QUIET=True)
s = parser.get_structure("x", PDB)
model = s[0]

# Report chain composition
print("=== chains ===")
for ch in model:
    aas = [r for r in ch if is_aa(r, standard=True)]
    if not aas:
        continue
    seq = "".join(three_to_one(r.resname) for r in aas)
    nums = [r.id[1] for r in aas]
    print(f"chain {ch.id}: {len(aas)} aa  range {min(nums)}-{max(nums)}")
    print(f"  seq: {seq}")

atoms = Selection.unfold_entities(model, "A")
ns = NeighborSearch(atoms)

# PD-L1 = chain A, restrict to IgV crop 18-132. Partner = any other chain.
contacts = defaultdict(lambda: defaultdict(set))  # Aresnum -> partnerchain -> set partner resnum
for atom in atoms:
    res = atom.get_parent()
    ch = res.get_parent().id
    if ch != "A":
        continue
    rn = res.id[1]
    if rn < 18 or rn > 132:
        continue
    if not is_aa(res, standard=True):
        continue
    for near in ns.search(atom.coord, CUT, level="A"):
        nres = near.get_parent()
        nch = nres.get_parent().id
        if nch == "A":
            continue
        if not is_aa(nres, standard=True):
            continue
        contacts[rn][nch].add(nres.id[1])

# resname lookup
aname = {r.id[1]: r.resname for r in model["A"] if is_aa(r, standard=True)}
rows = []
for rn, parts in contacts.items():
    total = sum(len(v) for v in parts.values())
    try:
        aa1 = three_to_one(aname[rn])
    except Exception:
        aa1 = "X"
    rows.append((rn, aa1, total, {k: sorted(v) for k, v in parts.items()}))
rows.sort(key=lambda r: -r[2])
print("\n=== PD-L1 (chain A) interface residues vs partner chains, 4.5A heavy-atom ===")
for rn, aa1, total, parts in rows:
    print(f"A{rn}{aa1}  contacts={total}  partners={parts}")

json.dump([{"resnum": rn, "aa": aa1, "n_contacts": total, "partners": parts}
           for rn, aa1, total, parts in rows],
          open("./scratch/interface_5jds.json", "w"), indent=2)
print("\nwrote ./scratch/interface_5jds.json")
