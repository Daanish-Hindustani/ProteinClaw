from Bio.PDB import PDBParser
aa3to1 = {"ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E","GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V"}
p = PDBParser(QUIET=True)
s = p.get_structure("5eli", "/home/ubuntu/.proteinclaw/gpu-workspace/83fe7bb1d7c1/pdb_fetch_1/5ELI_chainA_crop20-131.pdb")
chain = s[0]["A"]
seq = "".join(aa3to1.get(r.resname,"X") for r in chain if r.id[0]==" ")
print(f"len={len(seq)}")
print(seq)
