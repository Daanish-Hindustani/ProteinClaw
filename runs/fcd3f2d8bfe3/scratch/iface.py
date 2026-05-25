import sys, math
from collections import defaultdict
CUT=4.5
three2one = {'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E','GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F','PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V'}
def load(pdb):
    atoms=[]  # (chain, resnum, resn, x,y,z)
    for line in open(pdb):
        if not line.startswith(("ATOM","HETATM")): continue
        if line[76:78].strip()=="H": continue
        ch=line[21]; rn=int(line[22:26]); resn=line[17:20].strip()
        x,y,z=float(line[30:38]),float(line[38:46]),float(line[46:54])
        atoms.append((ch,rn,resn,x,y,z))
    return atoms
pdb=sys.argv[1]; bch=sys.argv[2]; tch=sys.argv[3]
atoms=load(pdb)
A=[a for a in atoms if a[0]==bch]; B=[a for a in atoms if a[0]==tch]
# residue numbering in target: AF2 renumbers target chain B starting at 1.
# Map back to PDB resnum: crop started at 21, so target_resnum_pdb = af2_resnum + 20
contacts=defaultdict(set)
resn_map={}
for ca in A:
    for cb in B:
        d=math.dist(ca[3:],cb[3:])
        if d<=CUT:
            contacts[('A',ca[1],ca[2])].add(('B',cb[1],cb[2]))
            contacts[('B',cb[1],cb[2])].add(('A',ca[1],ca[2]))
para=sorted([k for k in contacts if k[0]=='A'], key=lambda k:-len(contacts[k]))
epi=sorted([k for k in contacts if k[0]=='B'], key=lambda k:-len(contacts[k]))
def fmt(k,off=0):
    return f"{k[0]}{k[1]+off}{three2one.get(k[2],'X')}"
print("=== PARATOPE (binder chain A), by #contacts ===")
for k in para[:10]:
    print(f"  {fmt(k)}  contacts={len(contacts[k])}")
print("=== EPITOPE (target chain B; PDBresnum=af2+20) ===")
for k in epi:
    print(f"  af2 {k[1]:3d} -> TREM2 {k[1]+20:3d} {three2one.get(k[2],'X')}  contacts={len(contacts[k])}")
hot={44,47,70,74}
hit=sorted({k[1]+20 for k in epi} & hot)
print("Targeted hotspots {44,47,70,74} contacted:", hit)
print(f"Epitope residue count: {len(epi)}; paratope: {len(para)}")
