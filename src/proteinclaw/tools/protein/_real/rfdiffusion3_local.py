"""Local subprocess backend for RFdiffusion3.

Mirrors the integration pattern in https://github.com/jasonkim8652/protein-design-mcp:
RFdiffusion is invoked as a subprocess of the conda-managed install at
``$RFDIFFUSION_PATH``. Inputs are written to a working directory; outputs
are parsed back into our `RFDiffusionOutputs` shape.

This backend requires:

- `RFDIFFUSION_PATH` env var pointing to the install root.
- A CUDA-capable GPU (CPU is unsupported by RFdiffusion3 in practice).
- The conda env documented in ``envs/rfdiffusion3.yml``.

Argument construction and output parsing are unit-testable without the
binary present. End-to-end runs are marked ``@pytest.mark.expensive``.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import httpx

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein._real._subprocess import (
    deterministic_run_id,
    run_subprocess,
)
from proteinclaw.tools.protein.rfdiffusion3 import (
    BackboneDesign,
    RFDiffusionBackend,
    RFDiffusionInputs,
    RFDiffusionOutputs,
)

_DEFAULT_TIMEOUT_SECONDS = 60 * 30  # 30 min ceiling per call

# 4-character RCSB ids (e.g. ``4HHB``). LLMs frequently append a chain
# letter like ``1UBQ_A``; we strip that suffix and treat it as ``1UBQ``
# rather than rejecting it — RFdiffusion's contig syntax handles chain
# selection separately, so there's no information lost. The optional
# 5-letter id form is rare and we don't accept it here — callers should
# pass a path for those.
_PDB_ID_RE = re.compile(r"^[0-9][A-Za-z0-9]{3}$")
_PDB_ID_WITH_CHAIN_RE = re.compile(r"^([0-9][A-Za-z0-9]{3})[_:]([A-Za-z])$")
_RCSB_PDB_FILE_URL = "https://files.rcsb.org/download/{pdb_id}.pdb"


class LocalRFDiffusionBackend:
    """Subprocess backend invoking the bundled `run_inference.py`.

    The path resolution is intentionally explicit: we want a hard error
    when `RFDIFFUSION_PATH` is unset, not a confusing `FileNotFoundError`
    deep in the subprocess code.
    """

    def __init__(
        self,
        *,
        install_path: Path | None = None,
        python_executable: str | None = None,
        output_dir: Path | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Resolve the RFdiffusion install path; record runtime knobs."""
        env_path = os.environ.get("RFDIFFUSION_PATH")
        if install_path is None and env_path is None:
            raise ToolExecutionError(
                "rfdiffusion3",
                "RFDIFFUSION_PATH env var unset and no install_path provided",
            )
        self._install = Path(install_path or env_path or "")
        self._python = python_executable or sys.executable
        self._output_dir = output_dir or Path(tempfile.gettempdir()) / "proteinclaw" / "rfdiffusion"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout_seconds

    def build_args(
        self,
        inputs: RFDiffusionInputs,
        run_dir: Path,
        *,
        resolved_target: str | None = None,
    ) -> list[str]:
        """Build the CLI argument list passed to `run_inference.py`.

        Public so unit tests can validate without invoking the subprocess.

        ``resolved_target`` is the on-disk path that ``diffuse`` produced
        from ``inputs.target_pdb_path`` (after fetching, if it was a PDB
        id). When the target is None and no ``resolved_target`` override
        is supplied either, RFdiffusion runs unconditional (de novo) and
        we omit ``inference.input_pdb`` entirely.
        """
        target = resolved_target if resolved_target is not None else inputs.target_pdb_path
        out_prefix = run_dir / "design"
        cmd = [
            self._python,
            str(self._install / "scripts" / "run_inference.py"),
            f"contigmap.contigs=[{inputs.contigs}]",
            f"inference.num_designs={inputs.num_designs}",
            f"inference.output_prefix={out_prefix}",
        ]
        if target is not None:
            cmd.insert(2, f"inference.input_pdb={target}")
        if inputs.hotspot_residues:
            joined = ",".join(inputs.hotspot_residues)
            cmd.append(f"ppi.hotspot_res=[{joined}]")
        return cmd

    async def diffuse(self, inputs: RFDiffusionInputs) -> RFDiffusionOutputs:
        """Invoke RFdiffusion and parse the resulting PDB filenames."""
        run_dir = self._output_dir / f"run_{deterministic_run_id(inputs.model_dump_json())}"
        run_dir.mkdir(parents=True, exist_ok=True)
        resolved_target = await self._resolve_target(inputs.target_pdb_path)
        args = self.build_args(inputs, run_dir, resolved_target=resolved_target)
        await run_subprocess(
            *args,
            cwd=run_dir,
            timeout_seconds=self._timeout,
            tool_name="rfdiffusion3",
        )
        designs = list(_collect_designs(run_dir))
        if not designs:
            raise ToolExecutionError(
                "rfdiffusion3",
                f"RFdiffusion produced no designs in {run_dir}",
            )
        return RFDiffusionOutputs(designs=tuple(designs))


    async def _resolve_target(self, target: str | None) -> str | None:
        """Turn a target spec into an on-disk PDB path RFdiffusion can read.

        Three cases:

        1. ``None`` — unconditional (de novo) run; return None.
        2. Path to an existing file — return it as-is.
        3. RCSB PDB id (e.g. ``4HHB``) — download to a cache dir under
           ``$INSTALL_PREFIX`` and return the cached path. Raises
           ``ToolExecutionError`` if neither a path nor a recognizable
           id matches; we deliberately do not silently fall through
           to "RFdiffusion sees the literal id".
        """
        if target is None:
            return None
        candidate = Path(target)
        if candidate.is_file():
            return str(candidate)
        # Accept ``1UBQ_A`` / ``1UBQ:A`` and treat as bare ``1UBQ`` —
        # RFdiffusion's contig string already encodes the chain, so the
        # suffix is redundant info from the LLM, not a different file.
        chain_suffixed = _PDB_ID_WITH_CHAIN_RE.match(target)
        pdb_id = chain_suffixed.group(1) if chain_suffixed else target
        if not _PDB_ID_RE.match(pdb_id):
            raise ToolExecutionError(
                "rfdiffusion3",
                f"target_pdb_path {target!r} is neither an existing file nor a "
                "4-character RCSB PDB id; pass a real path or a valid id.",
            )
        cache_dir = self._output_dir.parent / "rcsb_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / f"{pdb_id.lower()}.pdb"
        if not cached.is_file():
            url = _RCSB_PDB_FILE_URL.format(pdb_id=pdb_id.lower())
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url)
            except httpx.RequestError as e:
                raise ToolExecutionError(
                    "rfdiffusion3",
                    f"network error fetching PDB {pdb_id}: {e}",
                ) from e
            if resp.status_code != 200:
                raise ToolExecutionError(
                    "rfdiffusion3",
                    f"RCSB returned {resp.status_code} for PDB id {pdb_id}",
                )
            cached.write_text(resp.text, encoding="utf-8")
        return str(cached)


def _collect_designs(run_dir: Path) -> list[BackboneDesign]:
    """Parse `design_<N>.pdb` files from the run directory.

    RFdiffusion writes per-residue pLDDT in the B-factor column. We use
    the mean B-factor as a confidence estimate for ranking; downstream
    AlphaFold predictions provide the authoritative pLDDT.
    """
    designs: list[BackboneDesign] = []
    for pdb_path in sorted(run_dir.glob("design_*.pdb")):
        match = re.search(r"design_(\d+)\.pdb$", pdb_path.name)
        design_id = match.group(1) if match else pdb_path.stem
        plddt = _mean_bfactor(pdb_path)
        designs.append(
            BackboneDesign(
                design_id=design_id,
                pdb_path=str(pdb_path),
                plddt_estimate=plddt,
            )
        )
    return designs


def _mean_bfactor(pdb_path: Path) -> float:
    """Return mean B-factor over C-alpha atoms, normalized to 0-1."""
    values: list[float] = []
    for line in pdb_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("ATOM") or line[12:16].strip() != "CA":
            continue
        try:
            values.append(float(line[60:66].strip()))
        except ValueError:
            continue
    if not values:
        return 0.5
    mean = sum(values) / len(values)
    # RFdiffusion confidence can appear as either 0-1 or 0-100 depending on
    # the generated PDB; accept both so real runs are not scaled down 100x.
    if mean <= 1.0:
        return max(0.0, mean)
    return max(0.0, min(1.0, mean / 100.0))


_: type[RFDiffusionBackend] = LocalRFDiffusionBackend
