"""Local subprocess backend for ProteinMPNN.

Mirrors the integration in https://github.com/jasonkim8652/protein-design-mcp:
calls `protein_mpnn_run.py` from the install at ``$PROTEINMPNN_PATH``.
Runs on CPU or GPU; we keep the subprocess interface identical either way
and let the install handle device dispatch.

Outputs land as a FASTA file we parse into the schema's
`DesignedSequence` records.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein._real._subprocess import (
    deterministic_run_id,
    run_subprocess,
)
from proteinclaw.tools.protein.protein_mpnn import (
    DesignedSequence,
    ProteinMPNNBackend,
    ProteinMPNNInputs,
    ProteinMPNNOutputs,
)

_DEFAULT_TIMEOUT_SECONDS = 60 * 15  # 15 min ceiling


class LocalProteinMPNNBackend:
    """Subprocess backend invoking the bundled `protein_mpnn_run.py`."""

    def __init__(
        self,
        *,
        install_path: Path | None = None,
        python_executable: str | None = None,
        output_dir: Path | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Resolve the ProteinMPNN install path."""
        env_path = os.environ.get("PROTEINMPNN_PATH")
        if install_path is None and env_path is None:
            raise ToolExecutionError(
                "protein_mpnn",
                "PROTEINMPNN_PATH env var unset and no install_path provided",
            )
        self._install = Path(install_path or env_path or "")
        self._python = python_executable or sys.executable
        self._output_dir = (
            output_dir or Path(tempfile.gettempdir()) / "proteinclaw" / "protein_mpnn"
        )
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout_seconds

    def build_args(
        self,
        inputs: ProteinMPNNInputs,
        run_dir: Path,
        *,
        chains_to_design: str | None = None,
    ) -> list[str]:
        """Build the CLI argument list. Public for unit-testing.

        ``chains_to_design`` overrides ``inputs.chains_to_design`` so
        ``design()`` can pass an auto-detected value computed from the
        on-disk PDB. When neither is set, ProteinMPNN designs every
        chain (its default).
        """
        chains = chains_to_design if chains_to_design is not None else inputs.chains_to_design
        cmd = [
            self._python,
            str(self._install / "protein_mpnn_run.py"),
            "--pdb_path",
            inputs.backbone_pdb_path,
            "--out_folder",
            str(run_dir),
            "--num_seq_per_target",
            str(inputs.num_sequences),
            "--sampling_temp",
            str(inputs.sampling_temperature),
            "--seed",
            "37",
            "--batch_size",
            "1",
        ]
        if chains:
            cmd.extend(["--pdb_path_chains", chains])
        return cmd

    async def design(self, inputs: ProteinMPNNInputs) -> ProteinMPNNOutputs:
        """Invoke ProteinMPNN and parse the FASTA output.

        For multi-chain PDBs (typical of RFdiffusion binder runs:
        chain A is the fixed target, the designed binder is appended)
        we default ``--pdb_path_chains`` to the LAST chain in the file
        unless the caller explicitly opted out via
        ``inputs.chains_to_design`` set to something other than None.
        Single-chain PDBs design that one chain; the ProteinMPNN default
        already does the right thing there, so we don't add the flag.
        """
        run_dir = self._output_dir / f"run_{deterministic_run_id(inputs.model_dump_json())}"
        run_dir.mkdir(parents=True, exist_ok=True)
        chains = inputs.chains_to_design
        if chains is None:
            chains = _auto_detect_design_chain(Path(inputs.backbone_pdb_path))
        args = self.build_args(inputs, run_dir, chains_to_design=chains)
        await run_subprocess(
            *args,
            cwd=run_dir,
            timeout_seconds=self._timeout,
            tool_name="protein_mpnn",
        )

        # ProteinMPNN writes FASTA into seqs/<input_basename>.fa.
        fasta_files = list(run_dir.glob("seqs/*.fa"))
        if not fasta_files:
            raise ToolExecutionError(
                "protein_mpnn",
                f"ProteinMPNN produced no FASTA output in {run_dir}",
            )
        sequences = parse_protein_mpnn_fasta(fasta_files[0])
        if not sequences:
            raise ToolExecutionError("protein_mpnn", "FASTA output had no designed sequences")
        return ProteinMPNNOutputs(sequences=tuple(sequences))


def _auto_detect_design_chain(pdb_path: Path) -> str | None:
    """Return the design-chain letter(s) for ``pdb_path``.

    Convention:
      - Single-chain PDB → None (ProteinMPNN's default designs the
        only chain; no flag needed).
      - Multi-chain PDB → the **alphabetically last** chain ID. RFdiffusion
        binder runs preserve the input target's chain id (typically A)
        and emit the designed binder under the next id (B), regardless
        of which chain is written first in the file. Picking the
        alphabetically-last chain re-designs the binder and treats the
        target as fixed context — the standard binder-design intent.
        Callers who need a different policy must set
        ``ProteinMPNNInputs.chains_to_design`` explicitly.
      - Unreadable file → None; let ProteinMPNN raise its own error.
    """
    try:
        text = pdb_path.read_text(encoding="utf-8")
    except OSError:
        return None
    seen: set[str] = set()
    for line in text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        if len(line) <= 21:
            continue
        chain = line[21:22]
        if chain == " ":
            continue
        seen.add(chain)
    if len(seen) <= 1:
        return None
    return max(seen)


def parse_protein_mpnn_fasta(fasta_path: Path) -> list[DesignedSequence]:
    """Parse a ProteinMPNN FASTA file into `DesignedSequence` records.

    The header looks like ``>T=0.10, sample=1, score=1.234, seq_recovery=0.5``
    and the next non-header line is the sequence. The wild-type entry
    (``>... score=...`` with no ``sample=``) is skipped.

    Public so tests can exercise the parser without invoking ProteinMPNN.
    """
    designed: list[DesignedSequence] = []
    current_score: float | None = None
    is_wild_type = True
    for line in fasta_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            is_wild_type = "sample=" not in line
            current_score = _parse_score(line)
            continue
        if is_wild_type:
            continue
        if current_score is None:
            continue
        designed.append(DesignedSequence(sequence=line, score=current_score))
        current_score = None
    return designed


def _parse_score(header: str) -> float | None:
    """Pull the numeric `score=` value from a FASTA header line."""
    for token in header.lstrip(">").split(","):
        token = token.strip()
        if token.startswith("score="):
            try:
                return float(token.split("=", 1)[1])
            except ValueError:
                return None
    return None


_: type[ProteinMPNNBackend] = LocalProteinMPNNBackend
