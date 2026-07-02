"""Package import smoke tests."""

from __future__ import annotations

import importlib.util


def test_package_imports() -> None:
    import proteinclaw  # noqa: F401

    assert proteinclaw.__version__


def test_cli_module_is_removed() -> None:
    assert importlib.util.find_spec("proteinclaw.cli") is None
