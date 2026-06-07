from Bio.PDB import PDBParser
import numpy as np
p = PDBParser(QUIET=True)
s = p.get_structure("x", "/home/ubuntu/.proteinclaw/gpu-workspace/29c9603ba01d/pdb_fetch_0/5ELI_chainA_crop20-131.pdb")
A = s[0]["A"]

# Candidate exposed lateral residues
cands = [20,21,23,25,52,54,56,57,59,102,103,107,125,127,128,129,130,131]
# Also include the apical CDR set as a reference
apical = [44,47,71,74,76,78,98]

def cb(r):
    if "CB" in r: return r["CB"].coord
    return r["CA"].coord

pos = {rid: cb(A[rid]) for rid in cands+apical}

# Compute centroid of apical CDR ridge — defines the "apical face direction"
apical_c = np.mean([pos[r] for r in apical], axis=0)

# For each lateral candidate, distance from apical centroid (larger = more opposite-face)
print("residue  AA   dist-from-apical (Å)")
for rid in cands:
    aa = A[rid].resname
    d = np.linalg.norm(pos[rid] - apical_c)
    print(f"  A{rid:3d} {aa}  {d:6.2f}")
print(f"\n apical centroid is mean of: {apical}")

# Now find contiguous spatial cluster among lateral cands far from apical
far = [rid for rid in cands if np.linalg.norm(pos[rid]-apical_c) > 15]
print(f"\nlateral cands >15Å from apical centroid: {far}")
print("\npairwise distances among 'far' set:")
for i,a in enumerate(far):
    for b in far[i+1:]:
        d = np.linalg.norm(pos[a]-pos[b])
        if d < 14:
            print(f"  A{a}-A{b}: {d:.2f}Å")
