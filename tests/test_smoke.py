"""Smoke test confirming the package imports and exposes a version."""

from __future__ import annotations

import proteinclaw


def test_package_imports() -> None:
    assert proteinclaw.__version__
