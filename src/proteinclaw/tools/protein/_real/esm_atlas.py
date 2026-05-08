"""ESM Atlas REST backend for the AlphaFold tool's no-MSA path.

ESM Atlas exposes ESMFold as a public REST endpoint at
https://api.esmatlas.com/foldSequence/v1/pdb/. POST a sequence (plain text
body), receive a PDB string. No credentials required. Sequence length cap
is ~400 residues; longer sequences time out or are rejected.

Confidence metrics aren't returned by the endpoint — we extract a mean
pLDDT estimate from the B-factor column of the returned PDB (ESMFold
encodes per-residue pLDDT there). pTM is approximated from the same
distribution as a stand-in until we have a metric source for it.
"""

from __future__ import annotations

import statistics
import tempfile
from pathlib import Path

import httpx

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein._real._subprocess import deterministic_run_id
from proteinclaw.tools.protein.alphafold import FoldBackend, FoldInputs, FoldOutputs

_DEFAULT_URL = "https://api.esmatlas.com/foldSequence/v1/pdb/"
_DEFAULT_TIMEOUT_SECONDS = 120.0
_MAX_LENGTH = 400


class EsmAtlasBackend:
    """ESMFold via the ESM Atlas REST API.

    Used for the no-MSA path of the `alphafold` tool. When `inputs.msa` is
    provided, we don't honour it (this endpoint is single-sequence only)
    and raise `ToolExecutionError` so the caller is forced to choose a
    backend that supports MSAs (e.g. local ColabFold).
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        url: str = _DEFAULT_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        output_dir: Path | None = None,
    ) -> None:
        """Bind an httpx client + an output directory for cached PDB files."""
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._url = url
        self._output_dir = output_dir or Path(tempfile.gettempdir()) / "proteinclaw" / "esm_atlas"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def fold(self, inputs: FoldInputs) -> FoldOutputs:
        """POST the sequence to ESM Atlas and return parsed FoldOutputs.

        Raises:
            ToolExecutionError: For network/HTTP/parse failures, sequences
                too long, or attempts to use an MSA against this backend.
        """
        if inputs.msa:
            raise ToolExecutionError(
                "alphafold",
                "ESM Atlas backend is single-sequence only; supply a local "
                "ColabFold backend for MSA-conditioned predictions.",
            )
        if len(inputs.sequence) > _MAX_LENGTH:
            raise ToolExecutionError(
                "alphafold",
                f"sequence length {len(inputs.sequence)} exceeds ESM Atlas cap of {_MAX_LENGTH}",
            )

        try:
            resp = await self._client.post(self._url, content=inputs.sequence.encode("utf-8"))
        except httpx.RequestError as e:
            raise ToolExecutionError("alphafold", f"network error contacting ESM Atlas: {e}") from e
        if resp.status_code >= 400:
            raise ToolExecutionError(
                "alphafold",
                f"ESM Atlas returned {resp.status_code}: {resp.text[:200]}",
            )
        pdb_text = resp.text
        if not pdb_text.startswith("PDB") and "ATOM" not in pdb_text[:200]:
            raise ToolExecutionError("alphafold", "ESM Atlas response was not a PDB")

        plddt = _mean_plddt_from_pdb(pdb_text)
        out_path = self._output_dir / f"esm_{deterministic_run_id(inputs.sequence)}.pdb"
        out_path.write_text(pdb_text, encoding="utf-8")
        return FoldOutputs(
            pdb_path=str(out_path),
            plddt=plddt,
            ptm=plddt,  # pTM not directly returned; use plddt as a proxy.
        )

    async def aclose(self) -> None:
        """Close the bound httpx client if we created it."""
        if self._owns_client:
            await self._client.aclose()


def _mean_plddt_from_pdb(pdb_text: str) -> float:
    """Extract mean pLDDT from the B-factor column of CA records.

    ESMFold writes per-residue pLDDT (0-100 scale) into the B-factor of
    each C-alpha. Returns the mean rescaled to 0-1, clamped.
    """
    values: list[float] = []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        # C-alpha atoms only; col 13-16 (1-indexed) hold the atom name.
        if line[12:16].strip() != "CA":
            continue
        # B-factor is columns 61-66 in PDB format.
        try:
            bf = float(line[60:66].strip())
        except ValueError:
            continue
        values.append(bf)
    if not values:
        return 0.0
    mean = statistics.fmean(values) / 100.0
    return max(0.0, min(1.0, mean))


_: type[FoldBackend] = EsmAtlasBackend
