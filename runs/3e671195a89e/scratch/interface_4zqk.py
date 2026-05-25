# Independent due-diligence: PD-L1 (chain A) epitope residues contacting PD-1 (chain B) in 4ZQK.
# Contact criterion (<=4.5 A heavy-atom) + BSA criterion (>=5 A^2 buried) per skill 9b.
import sys, tempfile, os
from collections import defaultdict
from Bio.PDB import PDBParser, NeighborSearch, Selection, PDBIO, Select
import freesasa

PDB = "/home/ubuntu/.cache/proteinclaw/pdb/4ZQK.pdb"
TARGET = "A"   # PD-L1 IgV
PARTNER = "B"  # PD-1
CONTACT = 4.5
BSA_CUT = 5.0
THREE2ONE = {
 'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E','GLY':'G',
 'HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F','PRO':'P','SER':'S',
 'THR':'T','TRP':'W','TYR':'Y','VAL':'V'}

parser = PDBParser(QUIET=True)
cx = parser.get_structure("cx", PDB)
model = cx[0]
atoms = [a for a in Selection.unfold_entities(model, "A")
         if a.get_parent().get_parent().id in (TARGET, PARTNER)]
ns = NeighborSearch(atoms)

contacts = defaultdict(set)  # (resnum,resname) on target -> partner res ids
for atom in atoms:
    ch = atom.get_parent().get_parent().id
    if ch != TARGET: continue
    res = atom.get_parent()
    if res.id[0] != ' ': continue
    for near in ns.search(atom.coord, CONTACT, level="A"):
        if near.get_parent().get_parent().id != PARTNER: continue
        pres = near.get_parent()
        key = (res.id[1], res.resname)
        contacts[key].add(f"B{pres.id[1]}")

# BSA: SASA of target-only vs target within complex
class ChainSel(Select):
    def __init__(self, chains): self.chains=set(chains)
    def accept_chain(self, c): return c.id in self.chains

def write_sub(chains):
    io = PDBIO(); io.set_structure(cx)
    fd, path = tempfile.mkstemp(suffix=".pdb"); os.close(fd)
    io.save(path, ChainSel(chains)); return path

def res_sasa(path, only_chain):
    st = freesasa.Structure(path)
    r = freesasa.calc(st, freesasa.Parameters(
        {"algorithm": freesasa.LeeRichards, "probe-radius": 1.4}))
    out = defaultdict(float)
    for i in range(st.nAtoms()):
        if st.chainLabel(i).strip() != only_chain: continue
        out[int(st.residueNumber(i))] += r.atomArea(i)
    return out

p_iso = write_sub([TARGET]); p_cx = write_sub([TARGET, PARTNER])
sasa_iso = res_sasa(p_iso, TARGET)
sasa_cx  = res_sasa(p_cx, TARGET)
bsa = {rn: sasa_iso.get(rn,0)-sasa_cx.get(rn,0) for rn in sasa_iso}

rows = []
all_res = set(contacts) | {(rn, None) for rn,b in bsa.items() if b>=BSA_CUT}
# build resname map
resname = {res.id[1]: res.resname for res in model[TARGET] if res.id[0]==' '}
seen=set()
for (rn, rname) in all_res:
    if rn in seen: continue
    seen.add(rn)
    rname = resname.get(rn,'UNK')
    aa = THREE2ONE.get(rname,'X')
    nc = len(contacts.get((rn,rname), set()))
    b = bsa.get(rn,0.0)
    tags=[]
    if nc>0: tags.append("contact")
    if b>=BSA_CUT: tags.append("buried")
    rows.append((rn, aa, nc, round(b,1), "+".join(tags), sorted(contacts.get((rn,rname),set()))))

rows.sort(key=lambda r:(-r[2], -r[3]))
print(f"{'res':>6} {'aa':>2} {'contacts':>8} {'BSA_A2':>7}  tags / partners")
for rn,aa,nc,b,tags,partners in rows:
    print(f"A{rn:<5} {aa:>2} {nc:>8} {b:>7}  {tags}  {','.join(partners[:6])}")
print(f"\nTotal interface residues (contact OR buried): {len(rows)}")
print("Compact list (chain+num+aa):", ",".join(f"A{rn}{aa}" for rn,aa,_,_,_,_ in rows))
