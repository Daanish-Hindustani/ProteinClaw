three2one = {'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E','GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F','PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V'}
pdb="/home/ubuntu/.proteinclaw/gpu-workspace/fcd3f2d8bfe3/pdb_fetch_0/5UD7_chainA_crop21-129.pdb"
seen={}
for line in open(pdb):
    if not line.startswith("ATOM"): continue
    rn=int(line[22:26]); resn=line[17:20].strip()
    if rn not in seen: seen[rn]=resn
seq="".join(three2one[seen[r]] for r in sorted(seen))
print("len",len(seq))
print(seq)
print("first_res",min(seen),"last_res",max(seen))
