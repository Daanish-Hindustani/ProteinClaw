"""RFdiffusion3 tool wrapper.

Generates protein backbones from a contig string and optional hotspot
residues. The default backend is a deterministic mock; the real backend
(Phase 6) requires GPU + conda env and lives under `tools/protein/_real/`.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from proteinclaw.tools.base_tool import BaseTool
from proteinclaw.tools.protein._mock_helpers import seed_rng_from

# These regexes are deliberately strict. The real backend interpolates
# the values into Hydra-style CLI args (e.g. ``contigmap.contigs=[<value>]``);
# without validation an attacker-controlled string could escape the
# brackets and inject extra Hydra config keys (e.g. flipping output paths
# or enabling unsafe resolvers). Path-traversal-shaped target_pdb_path
# values are also rejected for the same reason.
_TARGET_PDB_PATH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")
_CONTIGS_RE = re.compile(r"^[A-Za-z0-9/\-, ]+$")
_HOTSPOT_RE = re.compile(r"^[A-Za-z][0-9]+$")

# A contig segment that pins residues from an existing chain looks like
# ``A1-50`` or ``B12-12`` — chain letter + start ``-`` end. ``0 60-80``
# (a chain break followed by a free range) does NOT match because there
# is no leading letter on ``60-80``. We use this to enforce that any
# contig referencing a chain ALSO has a target_pdb_path supplied.
_CHAIN_REF_RE = re.compile(r"\b[A-Za-z]\d+-\d+\b")


class RFDiffusionInputs(BaseModel):
    """Inputs for RFdiffusion3 backbone generation.

    All free-form string fields are validated with strict regexes so
    they can be safely interpolated into the Hydra CLI of the local
    backend. See module-level constants for the allowed character sets.

    Attributes:
        target_pdb_path: Path, RCSB PDB id, or None. Provide a path/id when
            designing AGAINST a target (binders, motif scaffolding around a
            site). Leave None for unconditional de novo monomer generation.
            When set, the value must match ``[A-Za-z0-9._/-]+`` (no
            spaces, shell metacharacters, or ``=``) so it can be safely
            interpolated into the Hydra CLI of the local backend.
        contigs: Contig string declaring fixed/free residue ranges.
            Allowed: alphanumerics, ``/``, ``-``, ``,``, and spaces.
        hotspot_residues: Residues on the target the design should engage.
            Each must match ``[A-Za-z][0-9]+`` (e.g. ``A45``). Only
            meaningful when `target_pdb_path` is set.
        num_designs: How many backbones to sample.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_pdb_path: str | None = None
    contigs: str
    hotspot_residues: tuple[str, ...] = ()
    num_designs: int = Field(default=4, ge=1, le=64)

    @field_validator("target_pdb_path")
    @classmethod
    def _check_target_pdb_path(cls, value: str | None) -> str | None:
        """Reject any character that could break out of the Hydra arg.

        ``None`` is allowed (unconditional de novo); empty strings are
        not — they would silently coerce to a no-target run when the
        caller probably meant to provide one.
        """
        if value is None:
            return None
        if not value or not _TARGET_PDB_PATH_RE.match(value):
            raise ValueError(f"invalid target_pdb_path: {value!r}")
        return value

    @field_validator("contigs")
    @classmethod
    def _check_contigs(cls, value: str) -> str:
        """Reject brackets, equals, semicolons — Hydra control characters."""
        if not value or not _CONTIGS_RE.match(value):
            raise ValueError(f"invalid contigs: {value!r}")
        return value

    @field_validator("hotspot_residues")
    @classmethod
    def _check_hotspots(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Each hotspot must be chain-letter + residue number (e.g. ``A45``)."""
        for residue in value:
            if not _HOTSPOT_RE.match(residue):
                raise ValueError(f"invalid hotspot residue: {residue!r}")
        return value

    @model_validator(mode="after")
    def _check_target_required_when_contigs_reference_chain(self) -> RFDiffusionInputs:
        """A contig like ``A1-150/0 70-90`` pins residues from chain A of an
        existing structure — those residues only exist if ``target_pdb_path``
        points at the structure that defines them. Without a target,
        RFdiffusion crashes deep inside the sampler with an opaque traceback;
        we'd rather raise a clear validation error here so the LLM driving
        the loop sees a fixable observation.

        Hotspot residues have the same dependency: ``A45`` only resolves
        against a target. We enforce both.
        """
        if self.target_pdb_path is None:
            if self.contigs and _CHAIN_REF_RE.search(self.contigs):
                raise ValueError(
                    f"contigs {self.contigs!r} reference an existing chain; "
                    "target_pdb_path must be set (path or RCSB id)."
                )
            if self.hotspot_residues:
                raise ValueError(
                    f"hotspot_residues {list(self.hotspot_residues)!r} are only "
                    "meaningful with a target; set target_pdb_path or drop them."
                )
        return self


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
                pdb_path=f"/mock/rfdiffusion/{inputs.target_pdb_path or 'denovo'}/design-{i:03d}.pdb",
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
