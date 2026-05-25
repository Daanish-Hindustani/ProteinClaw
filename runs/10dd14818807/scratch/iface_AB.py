# Contact-based interface: chain A (PD-L1 IgV) residues within 5.0 A (heavy atoms)
# of chain B in 5JDS. Reports A-side residues sorted by num heavy contacts.
import sys
from collections import defaultdict
from Bio.PDB import PDBParser, NeighborSearch, Selection

CUTOFF = 5.0
THREE2ONE = {
 'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E',
 'GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F',
 'PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V'}

pdb = sys.argv[1]
s = PDBParser(QUIET=True).get_structure("x", pdb)[0]
atoms = [a for a in Selection.unfold_entities(s, "A") if a.element != 'H']
ns = NeighborSearch(atoms)

contacts = defaultdict(set)   # (A resnum, resname) -> set of B resnums
for atom in atoms:
    ch = atom.get_parent().get_parent().id
    if ch != 'A':
        continue
    res = atom.get_parent()
    if res.id[0] != ' ':
        continue  # skip hetero/water
    rn = res.id[1]
    if not (18 <= rn <= 132):
        continue  # IgV crop only
    for near in ns.search(atom.coord, CUTOFF, level="A"):
        if near.get_parent().get_parent().id == 'B' and near.get_parent().id[0] == ' ':
            contacts[(rn, res.resname)].add(near.get_parent().id[1])

rows = sorted(contacts.items(), key=lambda kv: -len(kv[1]))
print(f"PD-L1 chain A IgV residues within {CUTOFF} A of chain B partner:")
print(f"{'res':>10} {'#B-contacts':>12}")
for (rn, rname), partners in rows:
    aa = THREE2ONE.get(rname, 'X')
    print(f"  A{rn}{aa:<3} ({rname}) {len(partners):>5}")
print(f"\nTotal A-side interface residues: {len(rows)}")
print("Compact list:", ",".join(f"A{rn}" for (rn,_),_ in rows))
