"""ProteinMPNN tool wrapper.

Sequence design conditioned on a backbone PDB. Default backend is a
deterministic mock.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from proteinclaw.tools.base_tool import BaseTool
from proteinclaw.tools.protein._mock_helpers import seed_rng_from

_AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


class ProteinMPNNInputs(BaseModel):
    """Inputs for ProteinMPNN sequence design.

    Attributes:
        backbone_pdb_path: PDB file ProteinMPNN will read.
        num_sequences: Per-target sample count.
        sampling_temperature: Temperature for the autoregressive sampler.
        chains_to_design: Whitespace-separated chain letters to design
            (e.g. ``"B"`` for a binder, ``"A B"`` for both). When None
            the local backend auto-detects: single-chain PDB → that
            chain; multi-chain → designs only the LAST chain in the file
            (RFdiffusion convention writes the designed binder last).
            Mock backend ignores this field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backbone_pdb_path: str
    num_sequences: int = Field(default=8, ge=1, le=128)
    sampling_temperature: float = Field(default=0.1, gt=0.0, le=2.0)
    chains_to_design: str | None = None

    @field_validator("chains_to_design", mode="before")
    @classmethod
    def _coerce_chain_list(cls, value: object) -> object:
        """Accept ``["A", "B"]`` and ``"A B"`` interchangeably.

        LLM tool callers reliably emit JSON arrays for "list of chains";
        forcing them to know the underlying CLI takes a space-separated
        string just creates a class of validation errors with no upside.
        Normalize early — empty / blank lists become None so the auto-
        detect path takes over.
        """
        if value is None:
            return None
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            if not cleaned:
                return None
            return " ".join(cleaned)
        return value


class DesignedSequence(BaseModel):
    """One designed sequence with a fitness score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: str
    score: float


class ProteinMPNNOutputs(BaseModel):
    """Sequences produced by ProteinMPNN."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequences: tuple[DesignedSequence, ...]


@runtime_checkable
class ProteinMPNNBackend(Protocol):
    """Backend abstraction."""

    async def design(self, inputs: ProteinMPNNInputs) -> ProteinMPNNOutputs:
        """Design sequences for `inputs` and return them as `ProteinMPNNOutputs`."""
        ...


class MockProteinMPNNBackend:
    """Deterministic mock returning random plausible amino-acid sequences."""

    async def design(self, inputs: ProteinMPNNInputs) -> ProteinMPNNOutputs:
        """Sample `num_sequences` mock sequences seeded by the inputs."""
        rng = seed_rng_from(inputs.model_dump())
        length = 80  # plausible mock length; real MPNN reads from the backbone
        sequences = tuple(
            DesignedSequence(
                sequence="".join(rng.choice(_AMINO_ACIDS) for _ in range(length)),
                score=round(rng.uniform(0.3, 1.2), 4),
            )
            for _ in range(inputs.num_sequences)
        )
        return ProteinMPNNOutputs(sequences=sequences)


class ProteinMPNN(BaseTool):
    """Backbone-conditioned sequence designer (ProteinMPNN)."""

    name = "protein_mpnn"
    description = (
        "Design amino-acid sequences for a given backbone PDB. "
        "Use after backbone generation (e.g. RFdiffusion3) to produce candidate sequences."
    )
    input_schema = ProteinMPNNInputs
    output_schema = ProteinMPNNOutputs

    def __init__(self, backend: ProteinMPNNBackend | None = None) -> None:
        """Bind a backend; defaults to the deterministic mock."""
        self._backend: ProteinMPNNBackend = backend or MockProteinMPNNBackend()

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        """Delegate to the backend."""
        assert isinstance(inputs, ProteinMPNNInputs)
        return await self._backend.design(inputs)
