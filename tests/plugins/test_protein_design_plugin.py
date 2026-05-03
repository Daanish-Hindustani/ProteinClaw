import json
import sys
from pathlib import Path

import yaml

from hermes_cli.plugins import PluginManager, PluginManifest


PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "protein-design"
SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "protein-design"


def _load_plugin_modules():
    manifest = PluginManifest(
        name="protein-design",
        source="bundled",
        path=str(PLUGIN_DIR),
        key="protein-design",
    )
    mgr = PluginManager()
    mgr._load_plugin(manifest)
    return sys.modules["hermes_plugins.protein_design.tools"], mgr


def _write_pdb(path: Path):
    lines = []
    atom_id = 1
    for chain, residues in {"A": range(1, 6), "B": range(10, 13)}.items():
        for resi in residues:
            lines.append(
                f"ATOM  {atom_id:5d}  CA  ALA {chain}{resi:4d}    "
                f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C\n"
            )
            atom_id += 1
    path.write_text("".join(lines), encoding="utf-8")


def _write_cif(path: Path):
    path.write_text(
        """data_test
_refine.ls_d_res_high 1.8
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
ATOM 1 C CA ALA X 1 0.0 0.0 0.0 2 ALA A
ATOM 2 C CA ALA X 2 0.0 0.0 0.0 3 ALA A
ATOM 3 C CA ALA X 4 0.0 0.0 0.0 5 ALA A
ATOM 4 C CA ALA Y 1 0.0 0.0 0.0 10 ALA B
HETATM 5 C C1 CRO X 3 0.0 0.0 0.0 4 CRO A
#
""",
        encoding="utf-8",
    )


def test_plugin_registers_all_tools():
    _, mgr = _load_plugin_modules()
    loaded = mgr._plugins["protein-design"]
    assert loaded.enabled is True
    assert set(loaded.tools_registered) >= {
        "pubmed_search",
        "uniprot_search",
        "rcsb_search",
        "inspect_structure",
        "rfd3_design",
        "protein_mpnn_design",
        "esmfold_predict",
        "alphafold2_multimer_predict",
    }


def test_rfd3_contig_validation_accepts_binder_and_motif(tmp_path):
    tools, _ = _load_plugin_modules()
    pdb = tmp_path / "target.pdb"
    _write_pdb(pdb)

    assert tools.validate_rfd3_contig(
        mode="binder",
        contig="70-110,/0,A1-5",
        target_pdb_path=str(pdb),
        hotspot_residues=["A2", "A3-4"],
    ) == []

    assert tools.validate_rfd3_contig(
        mode="motif_scaffold",
        contig="30-50,A2-4,40-70",
        target_pdb_path=str(pdb),
        hotspot_residues=[],
    ) == []


def test_rfd3_contig_validation_rejects_bad_chain_and_range(tmp_path):
    tools, _ = _load_plugin_modules()
    pdb = tmp_path / "target.pdb"
    _write_pdb(pdb)

    errors = tools.validate_rfd3_contig(
        mode="binder",
        contig="70-110,/0,C1-5",
        target_pdb_path=str(pdb),
        hotspot_residues=["A99"],
    )

    assert any("missing chain C" in err for err in errors)
    assert any("missing residues" in err for err in errors)


def test_rfd3_contig_validation_reads_cif_auth_chain_and_residue_ids(tmp_path):
    tools, _ = _load_plugin_modules()
    cif = tmp_path / "target.cif"
    _write_cif(cif)

    assert tools.validate_rfd3_contig(
        mode="binder",
        contig="70-110,/0,A2-3",
        target_pdb_path=str(cif),
        hotspot_residues=["B10"],
    ) == []

    errors = tools.validate_rfd3_contig(
        mode="binder",
        contig="70-110,/0,A2-5",
        target_pdb_path=str(cif),
        hotspot_residues=[],
    )

    assert any("missing residues" in err for err in errors)


def test_rfd3_free_generation_uses_bare_lengths():
    tools, _ = _load_plugin_modules()
    assert tools.validate_rfd3_contig(
        mode="free_generation",
        contig="80-120",
        target_pdb_path="",
        hotspot_residues=[],
    ) == []
    assert tools.validate_rfd3_contig(
        mode="free_generation",
        contig="A1-20,80",
        target_pdb_path="",
        hotspot_residues=[],
    )


def test_rfd3_argument_translation():
    tools, _ = _load_plugin_modules()
    command = tools.build_rfd3_docker_args(
        input_path="/work/in.json",
        out_dir="/work/out",
        output_name="run1",
        num_designs=12,
        guide_scale=2.0,
        num_timesteps=50,
    )
    assert "diffusion_batch_size=12" in command
    assert "inference_sampler.step_scale=2.0" in command
    assert "inference_sampler.num_timesteps=50" in command
    assert "prevalidate_inputs=True" in command
    assert "global_prefix=run1" in command


def test_pubmed_query_variants_are_multi_query():
    tools, _ = _load_plugin_modules()
    clients = sys.modules["hermes_plugins.protein_design.clients"]
    variants = clients.build_pubmed_query_variants("KRAS binder", article_types=["Review"])
    assert len(variants) >= 5
    assert any("review[Publication Type]" in variant for variant in variants)
    assert any('"KRAS binder"' == variant for variant in variants)


def test_rcsb_empty_response_returns_empty_results(monkeypatch):
    _tools, _ = _load_plugin_modules()
    clients = sys.modules["hermes_plugins.protein_design.clients"]

    monkeypatch.setattr(clients, "_get_json", lambda *args, **kwargs: {})

    result = clients.search_rcsb("ZFC3H1 no matching structure", max_results=5)

    assert result["results"] == []


def test_esmfold_payload_includes_num_recycles():
    tools, _ = _load_plugin_modules()
    payload = tools.build_esmfold_input_payload(
        {"num_recycles": 8, "chunk_size": 64, "max_tokens_per_batch": 1024},
        sequence=None,
        fasta_container_path="/work/in.fasta",
        output_container_dir="/work/out",
    )
    assert payload["fasta_path"] == "/work/in.fasta"
    assert payload["output_dir"] == "/work/out"
    assert payload["num_recycles"] == 8
    assert payload["chunk_size"] == 64


def test_mpnn_command_uses_current_foundry_arguments():
    tools, _ = _load_plugin_modules()
    command = tools.build_mpnn_docker_args(
        {"output_name": "mpnn_out", "num_sequences": 8, "temperature": 0.1, "designed_chains": "A"},
        "/work/backbone.cif.gz",
    )

    assert "--out_directory" in command
    assert command[command.index("--out_directory") + 1] == "/work/mpnn_out"
    assert "--number_of_batches" in command
    assert command[command.index("--number_of_batches") + 1] == "8"
    assert "--checkpoint_path" in command
    assert command[command.index("--checkpoint_path") + 1] == "/weights/proteinmpnn_v_48_020.pt"
    assert "--out_folder" not in command
    assert "--num_seq_per_target" not in command


def test_mpnn_schema_does_not_advertise_missing_soluble_model():
    _load_plugin_modules()
    schemas = sys.modules["hermes_plugins.protein_design.schemas"]
    enum = schemas.PROTEIN_MPNN_DESIGN_SCHEMA["parameters"]["properties"]["model_type"]["enum"]

    assert enum == ["protein_mpnn", "ligand_mpnn"]


def test_alphafold2_multimer_command_uses_colabfold_batch_defaults():
    tools, _ = _load_plugin_modules()
    command = tools.build_alphafold2_multimer_docker_args(
        {"num_recycles": 6},
        "/work/input.fasta",
        "/work/af2_out",
    )

    assert command == [
        "colabfold_batch",
        "--model-type", "alphafold2_multimer_v3",
        "--num-recycle", "6",
        "/work/input.fasta",
        "/work/af2_out",
    ]


def test_alphafold2_multimer_writes_binder_target_fasta(tmp_path, monkeypatch):
    tools, _ = _load_plugin_modules()
    monkeypatch.setattr(tools, "ensure_workspace", lambda path=None: tmp_path if path is None else path)

    fasta = tools._write_multimer_fasta(
        {"binder_sequence": "ACD", "target_sequence": "EFG"},
        "complex",
        tmp_path,
    )

    assert fasta.read_text(encoding="utf-8") == ">complex\nACD:EFG\n"


def test_rcsb_chain_summary_reports_ranges_and_gaps(tmp_path):
    _load_plugin_modules()
    clients = sys.modules["hermes_plugins.protein_design.clients"]
    cif = tmp_path / "target.cif"
    _write_cif(cif)

    summary = clients.summarize_structure_chains(cif)

    assert summary["A"]["range"] == "2-5"
    assert summary["A"]["continuous_ranges"] == ["2-3", "5"]
    assert summary["A"]["gaps"] == [4]
    assert summary["B"]["range"] == "10-10"


def test_rcsb_direct_pdb_id_lookup_bypasses_search(monkeypatch):
    _load_plugin_modules()
    clients = sys.modules["hermes_plugins.protein_design.clients"]

    def fake_get_json(url, params=None, timeout=30.0):
        assert "rcsbsearch" not in url
        return {"struct": {"title": "Superfolder GFP"}}

    monkeypatch.setattr(clients, "_get_json", fake_get_json)

    result = clients.search_rcsb("", pdb_ids=["2b3p", "2B3P", "bad"], max_results=5)

    assert result["search_type"] == "pdb_id"
    assert result["pdb_ids"] == ["2B3P"]
    assert result["results"][0]["pdb_id"] == "2B3P"
    assert result["results"][0]["title"] == "Superfolder GFP"


def test_inspect_structure_reports_chains_hetatm_and_resolution(tmp_path):
    tools, _ = _load_plugin_modules()
    cif = tmp_path / "target.cif"
    _write_cif(cif)

    result = json.loads(tools.handle_inspect_structure({"structure_path": str(cif)}))

    assert result["success"] is True
    assert result["format"] == "cif"
    assert result["resolution"] == 1.8
    assert result["chains"]["A"]["gaps"] == [4]
    assert result["hetatm_comp_ids"] == ["CRO"]
    assert result["hetatm_records"][0]["chain"] == "A"
    assert result["hetatm_records"][0]["residue_number"] == 4


def test_esmfold_requires_sequence_or_fasta():
    tools, _ = _load_plugin_modules()
    result = json.loads(tools.handle_esmfold_predict({"output_name": "empty"}))

    assert result["success"] is False
    assert "sequence or fasta_path" in result["error"]


def test_each_tool_has_associated_skill_with_valid_frontmatter():
    expected = {
        "protein-binder-design",
        "pubmed-search",
        "uniprot-search",
        "rcsb-search",
        "inspect-structure",
        "rfd3-design",
        "protein-mpnn-design",
        "esmfold-predict",
        "alphafold2-multimer-predict",
    }
    found = {path.parent.name for path in SKILL_DIR.glob("*/SKILL.md")}
    assert expected <= found

    for skill_file in SKILL_DIR.glob("*/SKILL.md"):
        content = skill_file.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        _, frontmatter, body = content.split("---", 2)
        parsed = yaml.safe_load(frontmatter)
        assert parsed["name"] == skill_file.parent.name
        assert parsed["description"]
        assert body.strip()
