"""RFdiffusion3 tool wrapper.

Generates protein backbones from a contig string and optional hotspot
residues. The default backend is a deterministic mock; the real backend
(Phase 6) requires GPU + conda env and lives under `tools/protein/_real/`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.tools.base_tool import BaseTool
from proteinclaw.tools.protein._mock_helpers import seed_rng_from


class RFDiffusionInputs(BaseModel):
    """Inputs for RFdiffusion3 backbone generation.

    Attributes:
        target_pdb_path: Path or PDB id of the target structure to design against.
        contigs: Contig string declaring fixed/free residue ranges.
        hotspot_residues: Residues on the target the design should engage.
        num_designs: How many backbones to sample.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_pdb_path: str
    contigs: str
    hotspot_residues: tuple[str, ...] = ()
    num_designs: int = Field(default=4, ge=1, le=64)


class BackboneDesign(BaseModel):
    """One generated backbone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: str
    pdb_path: str
    plddt_estimate: float = Field(ge=0.0, le=1.0)


class RFDiffusionOutputs(BaseModel):
    """Backbones produced by RFdiffusion3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    designs: tuple[BackboneDesign, ...]


@runtime_checkable
class RFDiffusionBackend(Protocol):
    """Backend abstraction. Phase 6 will add real implementations."""

    async def diffuse(self, inputs: RFDiffusionInputs) -> RFDiffusionOutputs:
        """Generate backbones for `inputs` and return them as `RFDiffusionOutputs`."""
        ...


class MockRFDiffusionBackend:
    """Deterministic mock returning fake but well-formed BackboneDesigns."""

    async def diffuse(self, inputs: RFDiffusionInputs) -> RFDiffusionOutputs:
        """Generate `num_designs` mock backbones seeded by the inputs."""
        rng = seed_rng_from(inputs.model_dump())
        designs = tuple(
            BackboneDesign(
                design_id=f"mock-{i:03d}",
                pdb_path=f"/mock/rfdiffusion/{inputs.target_pdb_path}/design-{i:03d}.pdb",
                plddt_estimate=round(rng.uniform(0.55, 0.95), 3),
            )
            for i in range(inputs.num_designs)
        )
        return RFDiffusionOutputs(designs=designs)


class RFDiffusion3(BaseTool):
    """Diffusion-based backbone generator (RFdiffusion3)."""

    name = "rfdiffusion3"
    description = (
        "Generate protein backbones from a target PDB plus a contig string. "
        "Use for binder, scaffold, and motif-design backbone sampling."
    )
    input_schema = RFDiffusionInputs
    output_schema = RFDiffusionOutputs

    def __init__(self, backend: RFDiffusionBackend | None = None) -> None:
        """Bind a backend; defaults to the deterministic mock."""
        self._backend: RFDiffusionBackend = backend or MockRFDiffusionBackend()

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        """Delegate to the backend (already validated against input_schema)."""
        assert isinstance(inputs, RFDiffusionInputs)
        return await self._backend.diffuse(inputs)
