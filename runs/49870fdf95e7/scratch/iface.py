import json,sys
from collections import defaultdict
from Bio.PDB import PDBParser, NeighborSearch, Selection
from Bio.PDB.Polypeptide import is_aa
_3="ALA A ARG R ASN N ASP D CYS C GLN Q GLU E GLY G HIS H ILE I LEU L LYS K MET M PHE F PRO P SER S THR T TRP W TYR Y VAL V".split()
M={_3[i]:_3[i+1] for i in range(0,len(_3),2)}
pdb,B,T=sys.argv[1],sys.argv[2],sys.argv[3]   # binder chain, target chain
s=PDBParser(QUIET=True).get_structure("x",pdb)[0]
atoms=Selection.unfold_entities(s,"A"); ns=NeighborSearch(atoms)
con=defaultdict(set)
for a in atoms:
    ch=a.get_parent().get_parent().id
    if ch not in (B,T): continue
    for n in ns.search(a.coord,4.5,level="A"):
        oc=n.get_parent().get_parent().id
        if oc==ch or oc not in (B,T): continue
        con[(ch,a.get_parent().id[1])].add((oc,n.get_parent().id[1]))
name={(c.id,r.id[1]):M.get(r.resname,"X") for c in s for r in c if is_aa(r,standard=True)}
def fmt(ch,rn,pdbnum=False):
    n = rn+17 if (pdbnum and ch==T) else rn
    return f"{name.get((ch,rn),'X')}{n}"
para=sorted([(rn,len(p)) for (c,rn),p in con.items() if c==B],key=lambda x:-x[1])
epi =sorted([(rn,len(p)) for (c,rn),p in con.items() if c==T],key=lambda x:-x[1])
print("PARATOPE (binder chain %s), by #contacts:"%B)
print("  "+", ".join(f"{fmt(B,rn)}({n})" for rn,n in para))
print("EPITOPE (target chain %s) — AF2crop# then PDB#, by #contacts:"%T)
print("  "+", ".join(f"{fmt(T,rn)}/PDB{name.get((T,rn),'X')}{rn+17}({n})" for rn,n in epi))
hot={37,39,98,104,106}  # I54,Y56,M115,A121,Y123 in 1-based crop
hit=[rn+17 for rn,_ in epi if rn in hot]
print("Intended hotspots engaged (PDB#):", sorted(hit), f"-> {len(hit)}/5")
