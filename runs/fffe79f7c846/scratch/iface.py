import numpy as np
from Bio.PDB import PDBParser, NeighborSearch
from Bio.PDB.SASA import ShrakeRupley
from Bio.PDB.Polypeptide import is_aa

PDB = "/home/ubuntu/.cache/proteinclaw/pdb/5ELI.pdb"
parser = PDBParser(QUIET=True)
s = parser.get_structure("x", PDB)
model = s[0]

# restrict to chain A residues 20-131 (the modeled Ig domain)
chainA = model["A"]
resA = [r for r in chainA if is_aa(r) and 20 <= r.id[1] <= 131]
print(f"chain A modeled residues 20-131: {len(resA)}")

# --- SASA on chain A alone (relative exposure) ---
from Bio.PDB import Structure, Model, Chain
sr = ShrakeRupley()
# build a structure with only chain A 20-131
import copy
solo = Structure.Structure("solo")
m2 = Model.Model(0)
c2 = Chain.Chain("A")
for r in resA:
    c2.add(r.copy())
m2.add(c2)
solo.add(m2)
sr.compute(solo, level="R")

# Max SASA per residue (Tien 2013 theoretical) for rel. accessibility
maxasa = {'A':129,'R':274,'N':195,'D':193,'C':167,'E':223,'Q':225,'G':104,
 'H':224,'I':197,'L':201,'K':236,'M':224,'F':240,'P':159,'S':155,
 'T':172,'W':285,'Y':263,'V':174}
three2one = {'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLU':'E',
 'GLN':'Q','GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M',
 'PHE':'F','PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V'}

hydrophobic = set('AVILMFWY')
exposed_hydrophobic = []
exposed_all = []
for r in solo[0]["A"]:
    aa = three2one.get(r.resname)
    if aa is None: continue
    rel = r.sasa / maxasa[aa]
    if rel > 0.25:
        exposed_all.append((r.id[1], aa, round(rel,2)))
        if aa in hydrophobic:
            exposed_hydrophobic.append((r.id[1], aa, round(rel,2)))

print("\nExposed hydrophobic residues (rel SASA>0.25):")
for x in exposed_hydrophobic: print(" ", x)

# spatial clustering of exposed hydrophobics (CB within 8A)
ca = {}
for r in resA:
    atom = 'CB' if 'CB' in r else 'CA'
    ca[r.id[1]] = r[atom].coord
hyd_ids = [i for i,_,_ in exposed_hydrophobic]
print("\nHydrophobic patch clusters (exposed hyd within 8A):")
seen=set()
for i in hyd_ids:
    if i in seen: continue
    clust=[i]
    for j in hyd_ids:
        if j!=i and np.linalg.norm(ca[i]-ca[j])<8.0:
            clust.append(j)
    if len(clust)>=2:
        for k in clust: seen.add(k)
        print("  cluster:", sorted(clust))

# --- crystallographic A-B interface (heavy-atom contacts <4.5A) ---
chainB = model["B"]
resB = [r for r in chainB if is_aa(r) and 20 <= r.id[1] <= 131]
atomsB = [a for r in resB for a in r]
ns = NeighborSearch(atomsB)
iface = {}
for r in resA:
    for a in r:
        near = ns.search(a.coord, 4.5)
        if near:
            iface[r.id[1]] = iface.get(r.id[1],0)+len(near)
print("\nChain A residues contacting chain B (<4.5A, crystal contact):")
for i in sorted(iface): print("  ", i, three2one.get(chainA[i].resname,'?'), iface[i])

# Known disease/ligand residues to check exposure
known = [38,42,46,47,52,62,66,67,74,76,87]
print("\nExposure of literature-relevant residues:")
for i in known:
    if i in solo[0]["A"]:
        r=solo[0]["A"][i]; aa=three2one.get(r.resname,'?')
        print(f"  {i}{aa}: relSASA={round(r.sasa/maxasa.get(aa,200),2)}")
