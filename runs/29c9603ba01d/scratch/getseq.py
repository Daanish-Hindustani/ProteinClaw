from Bio.PDB import PDBParser
from Bio.SeqUtils import seq1
p = PDBParser(QUIET=True)
s = p.get_structure("x","/home/ubuntu/.proteinclaw/gpu-workspace/29c9603ba01d/pdb_fetch_0/5ELI_chainA_crop20-131.pdb")
seq = "".join(seq1(r.resname) for r in s[0]["A"] if r.id[0]==" ")
print(seq)
print("len=", len(seq))
