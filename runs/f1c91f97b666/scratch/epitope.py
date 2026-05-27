"""Structural sandbox: derive the PD-1 epitope on PD-L1 IgV from 4ZQK.
Chain A = PD-L1, chain B = PD-1. Heavy-atom contacts <=4.5 A define epitope.
Also Shrake-Rupley SASA on isolated PD-L1 to flag exposed hydrophobic patches.
"""
import warnings
warnings.filterwarnings("ignore")
from Bio.PDB import PDBParser, NeighborSearch, Selection
from Bio.PDB.SASA import ShrakeRupley
from Bio.PDB.Polypeptide import is_aa

PDB = "/home/ubuntu/.cache/proteinclaw/pdb/4ZQK.pdb"
parser = PDBParser(QUIET=True)
s = parser.get_structure("x", PDB)
model = s[0]
pdl1 = model["A"]
pd1 = model["B"]

three2one = {
 'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E',
 'GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F',
 'PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V'}

# heavy atoms only
def heavy(chain):
    out=[]
    for res in chain:
        if not is_aa(res, standard=True):
            continue
        for atom in res:
            if atom.element != 'H':
                out.append(atom)
    return out

pd1_atoms = heavy(pd1)
ns = NeighborSearch(pd1_atoms)

CUT = 4.5
epitope = {}  # resid -> (resname, ncontacts, atomset)
for res in pdl1:
    if not is_aa(res, standard=True):
        continue
    resid = res.id[1]
    contacts = 0
    atomnames=set()
    for atom in res:
        if atom.element == 'H':
            continue
        near = ns.search(atom.coord, CUT)
        if near:
            contacts += len(near)
            atomnames.add(atom.name)
    if contacts > 0:
        epitope[resid] = (res.resname, contacts, sorted(atomnames))

print("=== PD-L1 (chain A) residues within %.1f A of PD-1 (chain B) ===" % CUT)
print("resid  aa  resname  #contacts  contacting_sidechain_atoms")
for resid in sorted(epitope):
    rn, nc, atoms = epitope[resid]
    aa = three2one.get(rn, 'X')
    sc = [a for a in atoms if a not in ('N','CA','C','O')]
    print(f"  A{resid:<4} {aa}   {rn}     {nc:<4}   {','.join(sc) if sc else '(backbone only)'}")

ranked = sorted(epitope.items(), key=lambda kv: -kv[1][1])
print("\n=== Ranked by contact count (top epitope residues) ===")
for resid,(rn,nc,atoms) in ranked[:12]:
    print(f"  A{resid} {three2one.get(rn,'X')} {rn}: {nc} contacts")

# SASA on isolated PD-L1 IgV (crop 18-132 region)
print("\n=== Relative SASA of epitope residues (isolated PD-L1 chain) ===")
# build isolated structure: just chain A
sr = ShrakeRupley()
# detach pd1 to compute SASA of PD-L1 alone
sr.compute(pdl1, level="R")
maxasa = {  # Tien 2013 theoretical max ASA
 'A':129,'R':274,'N':195,'D':193,'C':167,'Q':225,'E':223,'G':104,'H':224,
 'I':197,'L':201,'K':236,'M':224,'F':240,'P':159,'S':155,'T':172,'W':285,'Y':263,'V':174}
hydrophobic=set('AILMFWVY')
print("resid aa  relSASA(%)  exposed?  hydrophobic?")
for resid in sorted(epitope):
    rn = epitope[resid][0]
    aa = three2one.get(rn,'X')
    res = pdl1[(' ',resid,' ')] if (' ',resid,' ') in pdl1 else None
    if res is None:
        continue
    sasa = res.sasa
    rel = 100*sasa/maxasa.get(aa,200)
    print(f"  A{resid:<4} {aa}  {rel:6.1f}     {'yes' if rel>20 else 'no ':3}      {'YES' if aa in hydrophobic else ''}")
