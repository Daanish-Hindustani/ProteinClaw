"""Local ColabFold backend for the AlphaFold tool's MSA path.

ColabFold runs `colabfold_batch` from a conda env. When `inputs.msa` is
None, defer to the ESM Atlas backend (single-sequence is faster and
doesn't need GPU). When an MSA is supplied (or the caller wants
AlphaFold-quality predictions), call colabfold_batch with the sequence
written to a FASTA file. Output is a per-model PDB; we pick the
top-ranked one and read pLDDT/pTM from the JSON sidecar.

This backend is GPU-recommended; CPU fallback is supported but very slow.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein._real._subprocess import (
    deterministic_run_id,
    run_subprocess,
)
from proteinclaw.tools.protein.alphafold import FoldBackend, FoldInputs, FoldOutputs

_DEFAULT_TIMEOUT_SECONDS = 60 * 60  # 1 hour ceiling


class LocalColabFoldBackend:
    """ColabFold subprocess backend.

    Construct with the path to `colabfold_batch` (resolved from
    `COLABFOLD_BIN` if not provided). Inputs flow through a temporary
    FASTA file; the binary writes ranked PDBs and confidence JSON files
    to the run directory.
    """

    def __init__(
        self,
        *,
        binary_path: str | None = None,
        output_dir: Path | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        num_recycles: int = 3,
        amber_relax: bool = False,
    ) -> None:
        """Resolve the colabfold_batch binary."""
        env_bin = os.environ.get("COLABFOLD_BIN")
        if binary_path is None and env_bin is None:
            raise ToolExecutionError(
                "alphafold",
                "COLABFOLD_BIN env var unset and no binary_path provided",
            )
        self._binary = binary_path or env_bin or "colabfold_batch"
        self._output_dir = output_dir or Path(tempfile.gettempdir()) / "proteinclaw" / "colabfold"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout_seconds
        self._num_recycles = num_recycles
        self._amber_relax = amber_relax

    def build_args(self, fasta_path: Path, run_dir: Path) -> list[str]:
        """Build the colabfold_batch CLI args. Public for unit testing."""
        cmd = [
            self._binary,
            str(fasta_path),
            str(run_dir),
            "--num-recycle",
            str(self._num_recycles),
            "--rank",
            "plddt",
            "--num-models",
            "1",
        ]
        if self._amber_relax:
            cmd.extend(["--amber"])
        return cmd

    async def fold(self, inputs: FoldInputs) -> FoldOutputs:
        """Run colabfold_batch on the input sequence."""
        run_dir = self._output_dir / f"run_{deterministic_run_id(inputs.sequence)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        fasta_path = run_dir / "input.fasta"
        fasta_path.write_text(f">query\n{inputs.sequence}\n", encoding="utf-8")

        args = self.build_args(fasta_path, run_dir)
        await run_subprocess(
            *args, cwd=run_dir, timeout_seconds=self._timeout, tool_name="alphafold"
        )

        pdb_path = _pick_top_pdb(run_dir)
        plddt, ptm = _read_confidence(run_dir)
        return FoldOutputs(pdb_path=str(pdb_path), plddt=plddt, ptm=ptm)


def _pick_top_pdb(run_dir: Path) -> Path:
    """Return the top-ranked PDB written by colabfold_batch."""
    candidates = sorted(run_dir.glob("*_rank_001*.pdb"))
    if not candidates:
        candidates = sorted(run_dir.glob("*.pdb"))
    if not candidates:
        raise ToolExecutionError("alphafold", f"colabfold produced no PDB in {run_dir}")
    return candidates[0]


def _read_confidence(run_dir: Path) -> tuple[float, float]:
    """Pull pLDDT + pTM from colabfold's `*_scores_rank_001*.json` sidecar."""
    score_files = sorted(run_dir.glob("*scores_rank_001*.json"))
    if not score_files:
        # Fall back to whatever scores we can find.
        score_files = sorted(run_dir.glob("*scores*.json"))
    if not score_files:
        return 0.0, 0.0
    body = json.loads(score_files[0].read_text(encoding="utf-8"))
    plddt_raw = body.get("plddt")
    plddt = _normalize_plddt(plddt_raw)
    ptm = float(body.get("ptm", 0.0))
    return plddt, max(0.0, min(1.0, ptm))


def _normalize_plddt(value: object) -> float:
    """Normalize a pLDDT value (or list thereof) into the 0-1 scale."""
    if isinstance(value, list):
        if not value:
            return 0.0
        mean = sum(float(v) for v in value) / len(value)
    elif isinstance(value, (int, float)):
        mean = float(value)
    else:
        return 0.0
    if mean > 1.5:  # Typical 0-100 range.
        mean = mean / 100.0
    return max(0.0, min(1.0, mean))


_: type[FoldBackend] = LocalColabFoldBackend
