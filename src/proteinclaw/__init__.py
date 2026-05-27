"""proteinclaw — agentic CLI for protein binder design.

Public surface intentionally tiny in v1: the package exposes a version string
and the registry singleton (re-exported for convenience). Most users interact
via the `proteinclaw` console script (see `proteinclaw.cli`).
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("proteinclaw")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
