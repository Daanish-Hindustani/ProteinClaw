"""Tool schemas for the protein-design plugin."""

from __future__ import annotations


PUBMED_SEARCH_SCHEMA = {
    "name": "pubmed_search",
    "description": (
        "Search PubMed with automatic query variation and return deduplicated "
        "paper metadata plus abstracts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Biomedical literature query."},
            "max_results": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            "date_range": {"type": "string", "description": "Optional PubMed date range, e.g. 2020:2026[pdat]."},
            "article_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional article type filters, e.g. Review, Journal Article.",
            },
            "query_variations": {"type": "boolean", "default": True},
        },
        "required": ["query"],
    },
}


UNIPROT_SEARCH_SCHEMA = {
    "name": "uniprot_search",
    "description": "Search UniProtKB for protein targets, annotations, features, and sequences.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free text or UniProt query syntax."},
            "organism_id": {"type": "string", "description": "Optional NCBI taxonomy ID, e.g. 9606."},
            "gene": {"type": "string", "description": "Optional gene symbol."},
            "reviewed_only": {"type": "boolean", "default": True},
            "max_results": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            "include_sequence": {"type": "boolean", "default": True},
        },
        "required": ["query"],
    },
}


RCSB_SEARCH_SCHEMA = {
    "name": "rcsb_search",
    "description": "Search RCSB PDB and optionally download structures for protein design workflows.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text, sequence, UniProt accession, or ligand query. Optional when pdb_ids is provided."},
            "pdb_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Known 4-character PDB IDs for direct lookup/download, e.g. ['2B3P']. Bypasses search.",
            },
            "search_type": {
                "type": "string",
                "enum": ["text", "sequence", "uniprot", "ligand"],
                "default": "text",
            },
            "max_results": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            "return_type": {
                "type": "string",
                "enum": ["entry", "polymer_entity", "assembly", "non_polymer_entity", "polymer_instance"],
                "default": "entry",
            },
            "download": {"type": "boolean", "default": False},
            "download_format": {
                "type": "string",
                "enum": ["cif", "pdb"],
                "default": "cif",
                "description": "Structure file format to download when download=true.",
            },
            "output_dir": {"type": "string", "description": "Directory for downloaded structure files."},
        },
        "required": [],
    },
}


INSPECT_STRUCTURE_SCHEMA = {
    "name": "inspect_structure",
    "description": "Inspect a local PDB/mmCIF structure file and return chain residue ranges, gaps, HETATM records, and resolution. Does not use Docker.",
    "parameters": {
        "type": "object",
        "properties": {
            "structure_path": {"type": "string", "description": "Local PDB, PDB.GZ, CIF, or CIF.GZ path to inspect."},
        },
        "required": ["structure_path"],
    },
}


RFD3_DESIGN_SCHEMA = {
    "name": "rfd3_design",
    "description": "Run RFdiffusion3 through an already-installed local Foundry Docker image using simplified protein-design inputs. Does not pull, build, or install Docker images.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["free_generation", "binder", "motif_scaffold", "partial_diffusion"],
            },
            "input_path": {"type": "string", "description": "Optional existing RFD3 JSON/YAML input spec."},
            "output_name": {"type": "string", "description": "Output folder/prefix name."},
            "num_designs": {"type": "integer", "default": 8, "minimum": 1, "maximum": 512},
            "contig": {"type": "string", "description": "RFD3 contig string."},
            "target_pdb_path": {"type": "string", "description": "Target PDB/CIF path for target-conditioned modes."},
            "hotspot_residues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Residue IDs such as A45 or ranges such as A45-52.",
            },
            "guide_scale": {"type": "number", "default": 1.5},
            "num_timesteps": {"type": "integer", "default": 200, "minimum": 1},
        },
        "required": ["mode", "output_name", "num_designs", "contig"],
    },
}


PROTEIN_MPNN_DESIGN_SCHEMA = {
    "name": "protein_mpnn_design",
    "description": "Run ProteinMPNN/LigandMPNN through an already-installed local Foundry Docker image. Does not pull, build, or install Docker images.",
    "parameters": {
        "type": "object",
        "properties": {
            "structure_path": {"type": "string", "description": "Single input PDB/CIF path, or a directory containing structure files."},
            "structure_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional explicit list of input PDB/CIF paths. Overrides structure_path when provided.",
            },
            "output_name": {"type": "string"},
            "num_sequences": {"type": "integer", "default": 16, "minimum": 1},
            "temperature": {"type": "number", "default": 0.1},
            "fixed_positions": {"type": "string"},
            "designed_chains": {"type": "string"},
            "model_type": {
                "type": "string",
                "enum": ["protein_mpnn", "ligand_mpnn"],
                "default": "protein_mpnn",
            },
        },
        "required": ["output_name"],
    },
}


ALPHAFOLD2_MULTIMER_PREDICT_SCHEMA = {
    "name": "alphafold2_multimer_predict",
    "description": "Run a configurable AlphaFold2/ColabFold multimer container to predict binder-target complex structures for interface triage. Requires a compatible AF2/ColabFold image.",
    "parameters": {
        "type": "object",
        "properties": {
            "fasta_path": {"type": "string", "description": "Input FASTA path. Used instead of sequence fields when provided."},
            "sequence": {"type": "string", "description": "Colon-separated multimer sequence, e.g. BINDER:TARGET."},
            "binder_sequence": {"type": "string", "description": "Designed binder amino-acid sequence."},
            "target_sequence": {"type": "string", "description": "Target amino-acid sequence."},
            "sequences": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered chain sequences. Used when fasta_path, sequence, and binder/target pair are not provided.",
            },
            "output_name": {"type": "string"},
            "model_type": {"type": "string", "default": "alphafold2_multimer_v3"},
            "num_recycles": {"type": "integer", "default": 3, "minimum": 1},
            "command": {
                "type": "string",
                "description": "Command inside the image. Defaults to colabfold_batch.",
            },
            "image": {"type": "string", "description": "Optional Docker image override."},
            "cpu_only": {"type": "boolean", "default": False},
        },
        "required": ["output_name"],
    },
}


ESMFOLD_PREDICT_SCHEMA = {
    "name": "esmfold_predict",
    "description": "Fold a provided protein sequence or FASTA locally with an already-installed ESMFold Docker image and return PDB paths/confidence metrics. Does not pull, build, or install Docker images.",
    "parameters": {
        "type": "object",
        "properties": {
            "sequence": {"type": "string", "description": "Amino acid sequence; use ':' between chains."},
            "fasta_path": {"type": "string", "description": "Input FASTA path. Used instead of sequence when provided."},
            "output_name": {"type": "string"},
            "num_recycles": {"type": "integer", "default": 4, "minimum": 1},
            "chunk_size": {"type": "integer", "description": "Optional axial attention chunk size: 128, 64, or 32."},
            "max_tokens_per_batch": {
                "type": "integer",
                "description": "Optional batching target; the HuggingFace image currently processes FASTA entries sequentially.",
            },
            "cpu_only": {"type": "boolean", "default": False},
            "cpu_offload": {"type": "boolean", "default": False},
        },
        "required": ["output_name"],
    },
}
