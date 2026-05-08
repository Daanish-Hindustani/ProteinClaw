"""Factory functions that build tool instances with backend selection.

Default is **`auto`** — pick the best real backend for each tool. Tests
override this via `tests/conftest.py` so CI stays deterministic and free
of network calls.

Resolution order, highest priority first:

1. Per-tool env var (e.g. `PROTEINCLAW_RCSB_BACKEND=mock`). One tool, one
   override.
2. Global env var `PROTEINCLAW_BACKEND` (e.g. `mock` or `auto`). Applies
   to every tool that has no per-tool override.
3. Built-in default: `auto`.

`auto` resolves per-tool:

- **RCSB** → REST (always works, public API).
- **Foldseek** → REST (public ticket-polling server).
- **AlphaFold** → `colabfold` if `COLABFOLD_BIN` is set, otherwise `esm_atlas`
  (no GPU, sequence cap ~400 aa).
- **RFdiffusion3** → `local` if `RFDIFFUSION_PATH` is set, otherwise raise
  with install instructions. There is no online fallback; users running
  binder design without the install must opt into mock explicitly.
- **ProteinMPNN** → `local` if `PROTEINMPNN_PATH` is set, otherwise raise
  with install instructions.
"""

from __future__ import annotations

import os

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein.alphafold import AlphaFold
from proteinclaw.tools.protein.foldseek import Foldseek
from proteinclaw.tools.protein.protein_mpnn import ProteinMPNN
from proteinclaw.tools.protein.rcsb import RCSB
from proteinclaw.tools.protein.rfdiffusion3 import RFDiffusion3
from proteinclaw.tools.registry import ToolRegistry
from proteinclaw.tools.sandbox_tool import SandboxTool

GLOBAL_ENV_VAR = "PROTEINCLAW_BACKEND"

_RCSB_VAR = "PROTEINCLAW_RCSB_BACKEND"
_FOLDSEEK_VAR = "PROTEINCLAW_FOLDSEEK_BACKEND"
_ALPHAFOLD_VAR = "PROTEINCLAW_ALPHAFOLD_BACKEND"
_RFDIFFUSION_VAR = "PROTEINCLAW_RFDIFFUSION_BACKEND"
_PROTEIN_MPNN_VAR = "PROTEINCLAW_PROTEIN_MPNN_BACKEND"


class UnknownBackendError(ValueError):
    """Raised when an env var names a backend the factory doesn't know."""


def _resolve_choice(per_tool_var: str, *, allowed: set[str]) -> str:
    """Resolve a per-tool backend choice.

    Order: per-tool env > `PROTEINCLAW_BACKEND` > "auto".
    """
    raw = os.environ.get(per_tool_var)
    if raw is None:
        raw = os.environ.get(GLOBAL_ENV_VAR, "auto")
    raw = raw.strip().lower()
    if raw not in allowed:
        raise UnknownBackendError(f"{per_tool_var}={raw!r} is not one of {sorted(allowed)}")
    return raw


def _missing_install_error(
    tool: str,
    *,
    install_path_var: str,
    backend_var: str,
    install_hint: str,
) -> ToolExecutionError:
    """Build a ToolExecutionError with a clear install instruction."""
    return ToolExecutionError(
        tool,
        f"{install_path_var} is unset; cannot run real backend without it. "
        f"Install with: {install_hint} — or override with "
        f"{backend_var}=mock for development.",
    )


def make_rcsb() -> RCSB:
    """Build the RCSB tool. `auto` → REST."""
    choice = _resolve_choice(_RCSB_VAR, allowed={"auto", "mock", "rest"})
    if choice in ("auto", "rest"):
        from proteinclaw.tools.protein._real.rcsb_rest import RcsbRestBackend

        return RCSB(backend=RcsbRestBackend())
    return RCSB()


def make_foldseek() -> Foldseek:
    """Build the Foldseek tool. `auto` → REST."""
    choice = _resolve_choice(_FOLDSEEK_VAR, allowed={"auto", "mock", "rest"})
    if choice in ("auto", "rest"):
        from proteinclaw.tools.protein._real.foldseek_rest import FoldseekRestBackend

        return Foldseek(backend=FoldseekRestBackend())
    return Foldseek()


def make_alphafold() -> AlphaFold:
    """Build AlphaFold. `auto` picks ColabFold local if installed, else ESM Atlas."""
    choice = _resolve_choice(_ALPHAFOLD_VAR, allowed={"auto", "mock", "esm_atlas", "colabfold"})
    if choice == "auto":
        choice = "colabfold" if os.environ.get("COLABFOLD_BIN") else "esm_atlas"
    if choice == "esm_atlas":
        from proteinclaw.tools.protein._real.esm_atlas import EsmAtlasBackend

        return AlphaFold(backend=EsmAtlasBackend())
    if choice == "colabfold":
        from proteinclaw.tools.protein._real.colabfold_local import (
            LocalColabFoldBackend,
        )

        return AlphaFold(backend=LocalColabFoldBackend())
    return AlphaFold()


def make_rfdiffusion3() -> RFDiffusion3:
    """Build RFdiffusion3. `auto` requires `RFDIFFUSION_PATH` or raises."""
    choice = _resolve_choice(_RFDIFFUSION_VAR, allowed={"auto", "mock", "local"})
    if choice == "auto":
        if not os.environ.get("RFDIFFUSION_PATH"):
            raise _missing_install_error(
                "rfdiffusion3",
                install_path_var="RFDIFFUSION_PATH",
                backend_var=_RFDIFFUSION_VAR,
                install_hint=(
                    "mamba env create -f envs/rfdiffusion3.yml && "
                    "git clone https://github.com/RosettaCommons/RFdiffusion /opt/RFdiffusion3 && "
                    "export RFDIFFUSION_PATH=/opt/RFdiffusion3"
                ),
            )
        choice = "local"
    if choice == "local":
        from proteinclaw.tools.protein._real.rfdiffusion3_local import (
            LocalRFDiffusionBackend,
        )

        return RFDiffusion3(
            backend=LocalRFDiffusionBackend(
                python_executable=os.environ.get("PROTEINCLAW_RFDIFFUSION_PYTHON"),
            )
        )
    return RFDiffusion3()


def make_protein_mpnn() -> ProteinMPNN:
    """Build ProteinMPNN. `auto` requires `PROTEINMPNN_PATH` or raises."""
    choice = _resolve_choice(_PROTEIN_MPNN_VAR, allowed={"auto", "mock", "local"})
    if choice == "auto":
        if not os.environ.get("PROTEINMPNN_PATH"):
            raise _missing_install_error(
                "protein_mpnn",
                install_path_var="PROTEINMPNN_PATH",
                backend_var=_PROTEIN_MPNN_VAR,
                install_hint=(
                    "mamba env create -f envs/protein_mpnn.yml && "
                    "git clone https://github.com/dauparas/ProteinMPNN /opt/ProteinMPNN && "
                    "export PROTEINMPNN_PATH=/opt/ProteinMPNN"
                ),
            )
        choice = "local"
    if choice == "local":
        from proteinclaw.tools.protein._real.protein_mpnn_local import (
            LocalProteinMPNNBackend,
        )

        return ProteinMPNN(
            backend=LocalProteinMPNNBackend(
                python_executable=os.environ.get("PROTEINCLAW_PROTEIN_MPNN_PYTHON"),
            )
        )
    return ProteinMPNN()


def build_default_registry() -> ToolRegistry:
    """Construct a `ToolRegistry` populated with every protein tool.

    Each tool's backend is decided by env vars at call time. Defaults to
    `auto` — REST backends for RCSB / Foldseek / AlphaFold and required-
    install backends for RFdiffusion3 / ProteinMPNN. Tests set
    `PROTEINCLAW_BACKEND=mock` via `tests/conftest.py`.

    Raises:
        ToolExecutionError: When a real GPU backend is required but its
            install path env var is unset. Override the specific tool to
            mock if needed.
    """
    registry = ToolRegistry()
    registry.register(make_rcsb())
    registry.register(make_rfdiffusion3())
    registry.register(make_protein_mpnn())
    registry.register(make_alphafold())
    registry.register(make_foldseek())
    # Sandbox is always real (subprocess) — no mock variant needed; the
    # underlying runner is already isolated.
    registry.register(SandboxTool())
    return registry
