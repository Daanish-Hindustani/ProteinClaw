"""Shared helpers for deterministic mock backends.

Mock backends produce stable, reproducible outputs from their inputs so that
fixtures stay deterministic and tests aren't flaky. The real backends in
Phase 6 ignore these helpers entirely.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any


def seed_rng_from(payload: dict[str, Any]) -> random.Random:
    """Return a `random.Random` seeded by a stable hash of `payload`.

    Uses `sorted(... default=str)` so dict order doesn't change the seed.
    SHA-256 is overkill for randomness but it's what the stdlib gives us
    without a dependency.
    """
    canonical = repr(sorted(payload.items(), key=lambda kv: kv[0]))
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big", signed=False)
    return random.Random(seed)
