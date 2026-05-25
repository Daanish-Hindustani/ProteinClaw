#!/usr/bin/env python3
"""Extract the PD-L1 (chain A) epitope contacted by the KN035 nanobody (chain B)
in 5JDS — the gold-standard co-crystal interface. Contact = any chain-A heavy
atom within 5.0 A of any chain-B heavy atom. Restrict to IgV crop 18-132."""
import sys
from collections import defaultdict
from Bio.PDB import PDBParser, NeighborSearch, Selection

PDB = "/home/ubuntu/.cache/proteinclaw/pdb/5JDS.pdb"
CUTOFF = 5.0
CROP = (18, 132)

aa3to1 = {
    'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E',
    'GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F',
    'PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V'}

parser = PDBParser(QUIET=True)
s = parser.get_structure("x", PDB)
model = s[0]
atoms = [a for a in Selection.unfold_entities(model, "A")
         if a.element != 'H']
ns = NeighborSearch(atoms)

contacts = defaultdict(set)        # (resnum, resname) -> set of chainB partner resnums
mindist = {}
for atom in atoms:
    ch = atom.get_parent().get_parent().id
    if ch != 'A':
        continue
    res = atom.get_parent()
    rn = res.id[1]
    if not (CROP[0] <= rn <= CROP[1]):
        continue
    for near in ns.search(atom.coord, CUTOFF, level='A'):
        if near.get_parent().get_parent().id != 'B':
            continue
        key = (rn, res.resname)
        contacts[key].add(near.get_parent().id[1])
        d = atom - near
        mindist[key] = min(mindist.get(key, 99), d)

rows = []
for (rn, rname), partners in contacts.items():
    rows.append((rn, rname, len(partners), round(mindist[(rn, rname)], 2)))
rows.sort(key=lambda r: (-r[2], r[3]))

print(f"PD-L1 (chain A) epitope residues within {CUTOFF} A of KN035 (chain B), crop {CROP}")
print(f"{'res':>10} {'1L':>3} {'#B-partners':>12} {'min_dist':>9}")
for rn, rname, npart, d in rows:
    one = aa3to1.get(rname, 'X')
    print(f"{rname}{rn:<6} {one:>3} {npart:>12} {d:>9}")
print(f"\nTotal epitope residues: {len(rows)}")
print("Compact list:", ",".join(f"A{rn}" for rn, _, _, _ in sorted(rows)))
