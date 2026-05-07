"""AlphaFold (and ESMFold alt) tool wrapper.

Structure prediction from a sequence. The two folders share an output shape
but differ on whether they consume an MSA — exposed here as a single tool
with an optional MSA input. The backend chooses how to handle it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.tools.base_tool import BaseTool
from proteinclaw.tools.protein._mock_helpers import seed_rng_from


class FoldInputs(BaseModel):
    """Inputs for structure prediction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: str = Field(min_length=10)
    msa: str | None = None  # None → ESMFold path; non-None → AlphaFold path


class FoldOutputs(BaseModel):
    """Predicted structure plus confidence metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pdb_path: str
    plddt: float = Field(ge=0.0, le=1.0)
    ptm: float = Field(ge=0.0, le=1.0)


@runtime_checkable
class FoldBackend(Protocol):
    """Backend abstraction (covers AlphaFold and ESMFold)."""

    async def fold(self, inputs: FoldInputs) -> FoldOutputs:
        """Predict structure for `inputs` and return `FoldOutputs`."""
        ...


class MockFoldBackend:
    """Deterministic mock returning plausible plddt/ptm values."""

    async def fold(self, inputs: FoldInputs) -> FoldOutputs:
        """Return a fake PDB path with stable plddt/ptm values."""
        rng = seed_rng_from(inputs.model_dump())
        msa_tag = "msa" if inputs.msa else "single"
        return FoldOutputs(
            pdb_path=f"/mock/fold/{msa_tag}/{rng.randrange(2**32):08x}.pdb",
            plddt=round(rng.uniform(0.45, 0.95), 3),
            ptm=round(rng.uniform(0.40, 0.90), 3),
        )


class AlphaFold(BaseTool):
    """Structure prediction from a sequence (AlphaFold; ESMFold path when msa is None)."""

    name = "alphafold"
    description = (
        "Predict a protein 3D structure from a sequence. Supply an MSA for "
        "AlphaFold-quality folding; omit it to fall back to ESMFold-style "
        "single-sequence prediction."
    )
    input_schema = FoldInputs
    output_schema = FoldOutputs

    def __init__(self, backend: FoldBackend | None = None) -> None:
        """Bind a backend; defaults to the deterministic mock."""
        self._backend: FoldBackend = backend or MockFoldBackend()

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        """Delegate to the backend."""
        assert isinstance(inputs, FoldInputs)
        return await self._backend.fold(inputs)
