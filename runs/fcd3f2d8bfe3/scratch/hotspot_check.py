import math
pdb="/home/ubuntu/.proteinclaw/gpu-workspace/fcd3f2d8bfe3/pdb_fetch_0/5UD7_chainA_crop21-129.pdb"
res={}  # resnum -> {atomname:(x,y,z), 'resn':..}
for line in open(pdb):
    if not line.startswith("ATOM"): continue
    rn=int(line[22:26]); an=line[12:16].strip(); resn=line[17:20].strip()
    x,y,z=float(line[30:38]),float(line[38:46]),float(line[46:54])
    res.setdefault(rn,{'resn':resn,'atoms':{}})['atoms'][an]=(x,y,z)

cand=[44,47,50,62,67,70,71,74,76]
print("Candidate residues present:")
for rn in cand:
    if rn in res:
        print(f"  {rn} {res[rn]['resn']} atoms={list(res[rn]['atoms'].keys())[:6]}")
    else:
        print(f"  {rn} MISSING")

def cb(rn):
    a=res[rn]['atoms']
    return a.get('CB', a.get('CA'))
# pairwise CB distances among candidates
print("\nPairwise CB distances (A):")
present=[rn for rn in cand if rn in res]
for i,a in enumerate(present):
    for b in present[i+1:]:
        pa,pb=cb(a),cb(b)
        d=math.dist(pa,pb)
        if d<16: print(f"  {a}-{b}: {d:.1f}")

# crude solvent exposure: count heavy atoms within 10A of each candidate's CB (lower = more exposed)
allatoms=[v for r in res.values() for v in r['atoms'].values()]
print("\nCrude burial (neighbors within 10A of CB, lower=more exposed):")
for rn in present:
    c=cb(rn); n=sum(1 for p in allatoms if math.dist(c,p)<10)
    print(f"  {rn} {res[rn]['resn']}: {n}")
