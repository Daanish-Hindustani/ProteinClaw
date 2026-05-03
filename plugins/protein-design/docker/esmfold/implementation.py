"""ESMFold structure prediction using the HuggingFace implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _parse_fasta(text: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    header: str | None = None
    parts: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                entries.append((header, "".join(parts).upper()))
            header = line[1:].strip() or f"sequence_{len(entries) + 1}"
            parts = []
            continue
        parts.append(line.replace(" ", ""))
    if header is not None:
        entries.append((header, "".join(parts).upper()))
    return [(name, seq) for name, seq in entries if seq]


def _load_entries(
    *,
    sequence: str | None,
    fasta_path: str | None,
    sequence_name: str | None,
) -> list[tuple[str, str]]:
    if bool(sequence) == bool(fasta_path):
        raise ValueError("Provide exactly one of sequence or fasta_path.")
    if fasta_path:
        entries = _parse_fasta(Path(fasta_path).read_text(encoding="utf-8"))
        if not entries:
            raise ValueError(f"No sequences found in FASTA file: {fasta_path}")
        return entries

    clean_sequence = "".join((sequence or "").split()).upper()
    if not clean_sequence:
        raise ValueError("Sequence must not be empty.")
    return [((sequence_name or "sequence").strip() or "sequence", clean_sequence)]


def _safe_name(header: str, fallback: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in header)
    return safe or fallback


def run(
    sequence: str | None = None,
    fasta_path: str | None = None,
    output_dir: str = "/work",
    sequence_name: str | None = None,
    num_recycles: int = 4,
    max_tokens_per_batch: int = 1024,
    chunk_size: int | None = None,
    cpu_only: bool = False,
    cpu_offload: bool = False,
    **_: Any,
) -> dict[str, Any]:
    import torch
    from transformers import AutoTokenizer, EsmForProteinFolding

    entries = _load_entries(sequence=sequence, fasta_path=fasta_path, sequence_name=sequence_name)
    device = "cpu" if cpu_only else ("cuda" if torch.cuda.is_available() else "cpu")
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained("facebook/esmfold_v1")
    model = EsmForProteinFolding.from_pretrained("facebook/esmfold_v1")
    if chunk_size is not None:
        set_chunk_size = getattr(model.trunk, "set_chunk_size", None)
        if callable(set_chunk_size):
            set_chunk_size(int(chunk_size))
    model = model.to(device)
    model.eval()

    predictions: list[dict[str, Any]] = []
    confidence_values: list[float] = []

    for index, (header, clean_sequence) in enumerate(entries, start=1):
        with torch.no_grad():
            tokenized = tokenizer([clean_sequence], return_tensors="pt", add_special_tokens=False)
            tokenized = {key: value.to(device) for key, value in tokenized.items()}
            output = model(**tokenized, num_recycles=int(num_recycles))

        pdb_string = model.output_to_pdb(output)[0]
        plddt_tensor = output["plddt"][0].detach().cpu()
        avg_plddt = plddt_tensor.mean().item() * 100
        confidence_values.append(avg_plddt)

        pdb_name = f"{_safe_name(header, f'sequence_{index}')}.pdb" if len(entries) > 1 else "predicted_structure.pdb"
        pdb_path = output_root / pdb_name
        pdb_path.write_text(pdb_string, encoding="utf-8")
        predictions.append(
            {
                "sequence_name": header,
                "num_residues": len(clean_sequence.replace(":", "")),
                "confidence": avg_plddt,
                "pdb_path": str(pdb_path),
            }
        )

    avg_confidence = sum(confidence_values) / len(confidence_values)
    notes: list[str] = []
    if len(entries) > 1 and max_tokens_per_batch:
        notes.append("FASTA entries were processed sequentially by the HuggingFace ESMFold implementation.")
    if cpu_offload:
        notes.append("CPU offload was requested but is not implemented in this image.")

    return {
        "summary": (
            f"ESMFold structure prediction completed for {len(entries)} sequence(s). "
            f"Average pLDDT confidence: {avg_confidence:.1f}/100."
        ),
        "confidence": avg_confidence,
        "predictions": predictions,
        "notes": notes,
    }
