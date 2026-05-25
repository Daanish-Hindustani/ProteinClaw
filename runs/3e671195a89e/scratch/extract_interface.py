# Paratope/epitope from an AF2 complex (contact <=4.5A + BSA >=5A^2). Skill 9b/9c.
# Maps target-chain (B) AF2 numbering back to native PD-L1 via --offset (AF2 resets to 1).
import sys, tempfile, os, json
from collections import defaultdict
from Bio.PDB import PDBParser, NeighborSearch, Selection, PDBIO, Select
from Bio.SeqUtils import seq1
import freesasa

pdb, binder, target, offset = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
CONTACT, BSA_CUT = 4.5, 5.0
HOTSPOTS = {56, 113, 115, 121, 123}  # native PD-L1 anchors we designed to

parser = PDBParser(QUIET=True)
cx = parser.get_structure("cx", pdb)[0]
atoms = [a for a in Selection.unfold_entities(cx, "A")
         if a.get_parent().get_parent().id in (binder, target)]
ns = NeighborSearch(atoms)
contacts = defaultdict(set)
for atom in atoms:
    ch = atom.get_parent().get_parent().id
    res = atom.get_parent()
    if res.id[0] != ' ': continue
    for near in ns.search(atom.coord, CONTACT, level="A"):
        och = near.get_parent().get_parent().id
        if och == ch or och not in (binder, target): continue
        contacts[(ch, res.id[1])].add((och, near.get_parent().id[1]))

class Sel(Select):
    def __init__(s, c): s.c=set(c)
    def accept_chain(s, c): return c.id in s.c
def sub(chains):
    io=PDBIO(); io.set_structure(cx); fd,p=tempfile.mkstemp(suffix=".pdb"); os.close(fd)
    io.save(p, Sel(chains)); return p
def sasa(path, ch):
    st=freesasa.Structure(path)
    r=freesasa.calc(st, freesasa.Parameters({"algorithm":freesasa.LeeRichards,"probe-radius":1.4}))
    out=defaultdict(float)
    for i in range(st.nAtoms()):
        if st.chainLabel(i).strip()==ch: out[int(st.residueNumber(i))]+=r.atomArea(i)
    return out
bsa={}
for ch in (binder, target):
    iso=sasa(sub([ch]), ch); com=sasa(sub([binder,target]), ch)
    bsa[ch]={rn: iso.get(rn,0)-com.get(rn,0) for rn in iso}
resname={ch:{r.id[1]:r.resname for r in cx[ch] if r.id[0]==' '} for ch in (binder,target)}

def native(ch, rn): return rn+offset if ch==target else rn
def build(ch, role):
    rows=[]
    keys=set(rn for (c,rn) in contacts if c==ch) | {rn for rn,b in bsa[ch].items() if b>=BSA_CUT}
    for rn in keys:
        aa=seq1(resname[ch].get(rn,'XAA'))
        parts=sorted(contacts.get((ch,rn),set()))
        nc=len(parts); b=round(bsa[ch].get(rn,0),1)
        tags=[];
        if nc>0: tags.append("contact")
        if b>=BSA_CUT: tags.append("buried")
        nat=native(ch,rn)
        if ch==target and nat in HOTSPOTS: tags.append("design_hotspot")
        rows.append({"native_resnum":nat,"af2_resnum":rn,"aa":aa,"num_heavy_contacts":nc,
                     "bsa_a2":b,"tags":tags,
                     "partners":[f"{c}{native(c,r)}" for c,r in parts]})
    rows.sort(key=lambda r:(-r["num_heavy_contacts"],-r["bsa_a2"]))
    return rows
para=build(binder,"paratope"); epi=build(target,"epitope")
print("=== PARATOPE (binder chain %s) top by contacts ==="%binder)
for r in para[:8]: print(f"  {binder}{r['af2_resnum']}{r['aa']}  contacts={r['num_heavy_contacts']} bsa={r['bsa_a2']} {'+'.join(r['tags'])}")
print("=== EPITOPE (target chain %s, native PD-L1 numbering) top by contacts ==="%target)
for r in epi[:10]: print(f"  {target}{r['native_resnum']}{r['aa']}  contacts={r['num_heavy_contacts']} bsa={r['bsa_a2']} {'+'.join(r['tags'])}")
hot_hit=sorted(r['native_resnum'] for r in epi if 'design_hotspot' in r['tags'])
print("Design hotspots engaged:", hot_hit, "of", sorted(HOTSPOTS))
json.dump({"paratope":para,"epitope":epi}, open(sys.argv[5],"w"), indent=2)
