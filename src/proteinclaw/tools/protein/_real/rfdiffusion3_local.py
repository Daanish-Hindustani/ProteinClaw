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

    def build_args(self, inputs: RFDiffusionInputs, run_dir: Path) -> list[str]:
        """Build the CLI argument list passed to `run_inference.py`.

        Public so unit tests can validate without invoking the subprocess.
        """
        out_prefix = run_dir / "design"
        cmd = [
            self._python,
            str(self._install / "scripts" / "run_inference.py"),
            f"inference.input_pdb={inputs.target_pdb_path}",
            f"contigmap.contigs=[{inputs.contigs}]",
            f"inference.num_designs={inputs.num_designs}",
            f"inference.output_prefix={out_prefix}",
        ]
        if inputs.hotspot_residues:
            joined = ",".join(inputs.hotspot_residues)
            cmd.append(f"ppi.hotspot_res=[{joined}]")
        return cmd

    async def diffuse(self, inputs: RFDiffusionInputs) -> RFDiffusionOutputs:
        """Invoke RFdiffusion and parse the resulting PDB filenames."""
        run_dir = self._output_dir / f"run_{deterministic_run_id(inputs.model_dump_json())}"
        run_dir.mkdir(parents=True, exist_ok=True)
        args = self.build_args(inputs, run_dir)
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
    # RFdiffusion reports raw pLDDT-like scores in 0-100; rescale and clamp.
    return max(0.0, min(1.0, mean / 100.0))


_: type[RFDiffusionBackend] = LocalRFDiffusionBackend
