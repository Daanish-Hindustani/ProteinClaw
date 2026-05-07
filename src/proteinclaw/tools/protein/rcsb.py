"""RCSB tool wrapper.

Fetches PDB metadata and sequence by id. Used at task intake to retrieve
target structures and at evaluation time for cross-references.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, field_validator

from proteinclaw.tools.base_tool import BaseTool
from proteinclaw.tools.protein._mock_helpers import seed_rng_from

_PDB_ID = re.compile(r"^[A-Za-z0-9]{4}$")
_AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


class RCSBInputs(BaseModel):
    """Inputs for an RCSB metadata fetch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pdb_id: str

    @field_validator("pdb_id")
    @classmethod
    def _check_pdb_id(cls, value: str) -> str:
        """Ensure the id is a 4-character alphanumeric PDB code, normalized to upper."""
        if not _PDB_ID.match(value):
            raise ValueError(f"invalid PDB id: {value!r}")
        return value.upper()


class RCSBOutputs(BaseModel):
    """Metadata returned for a single PDB id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pdb_id: str
    sequence: str
    length: int
    organism: str


@runtime_checkable
class RCSBBackend(Protocol):
    """Backend abstraction."""

    async def fetch(self, inputs: RCSBInputs) -> RCSBOutputs:
        """Fetch metadata for `inputs.pdb_id` and return `RCSBOutputs`."""
        ...


class MockRCSBBackend:
    """Deterministic mock returning fake metadata seeded by the PDB id."""

    async def fetch(self, inputs: RCSBInputs) -> RCSBOutputs:
        """Build a stable fake record for `inputs.pdb_id`."""
        rng = seed_rng_from(inputs.model_dump())
        length = rng.randint(80, 240)
        sequence = "".join(rng.choice(_AMINO_ACIDS) for _ in range(length))
        organism = rng.choice(("Homo sapiens", "Escherichia coli", "Mus musculus"))
        return RCSBOutputs(
            pdb_id=inputs.pdb_id,
            sequence=sequence,
            length=length,
            organism=organism,
        )


class RCSB(BaseTool):
    """RCSB PDB metadata fetcher."""

    name = "rcsb"
    description = (
        "Fetch sequence and metadata for a PDB id from the RCSB. "
        "Use to retrieve a target structure at task intake."
    )
    input_schema = RCSBInputs
    output_schema = RCSBOutputs

    def __init__(self, backend: RCSBBackend | None = None) -> None:
        """Bind a backend; defaults to the deterministic mock."""
        self._backend: RCSBBackend = backend or MockRCSBBackend()

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        """Delegate to the backend."""
        assert isinstance(inputs, RCSBInputs)
        return await self._backend.fetch(inputs)
