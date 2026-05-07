"""Foldseek tool wrapper.

Structural similarity search against a database. Used by the Evaluator's
novelty metric — a "no hits" result is a strong novelty signal.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.tools.base_tool import BaseTool
from proteinclaw.tools.protein._mock_helpers import seed_rng_from


class FoldseekInputs(BaseModel):
    """Inputs for a Foldseek similarity search."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_pdb_path: str
    database: str = "pdb"
    max_hits: int = Field(default=10, ge=1, le=1000)


class FoldseekHit(BaseModel):
    """One search hit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pdb_id: str
    tm_score: float = Field(ge=0.0, le=1.0)
    evalue: float = Field(ge=0.0)


class FoldseekOutputs(BaseModel):
    """Hits returned by Foldseek, sorted by descending TM-score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hits: tuple[FoldseekHit, ...]


@runtime_checkable
class FoldseekBackend(Protocol):
    """Backend abstraction."""

    async def search(self, inputs: FoldseekInputs) -> FoldseekOutputs:
        """Run a similarity search for `inputs` and return ranked hits."""
        ...


class MockFoldseekBackend:
    """Deterministic mock returning a few synthetic hits."""

    async def search(self, inputs: FoldseekInputs) -> FoldseekOutputs:
        """Generate up to `max_hits` synthetic hits seeded by the inputs."""
        rng = seed_rng_from(inputs.model_dump())
        n = min(inputs.max_hits, 5)
        raw = sorted(
            (
                FoldseekHit(
                    pdb_id=f"{rng.randrange(0, 16**4):04x}".upper(),
                    tm_score=round(rng.uniform(0.3, 0.95), 3),
                    evalue=round(rng.uniform(1e-20, 1e-2), 6),
                )
                for _ in range(n)
            ),
            key=lambda h: h.tm_score,
            reverse=True,
        )
        return FoldseekOutputs(hits=tuple(raw))


class Foldseek(BaseTool):
    """Structural similarity search."""

    name = "foldseek"
    description = (
        "Search a PDB structure against a database of known folds. "
        "Returns hits sorted by TM-score; few or low-score hits indicate novelty."
    )
    input_schema = FoldseekInputs
    output_schema = FoldseekOutputs

    def __init__(self, backend: FoldseekBackend | None = None) -> None:
        """Bind a backend; defaults to the deterministic mock."""
        self._backend: FoldseekBackend = backend or MockFoldseekBackend()

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        """Delegate to the backend."""
        assert isinstance(inputs, FoldseekInputs)
        return await self._backend.search(inputs)
