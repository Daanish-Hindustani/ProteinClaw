"""ProteinClaw CLI entry point.

Re-exports `main` so the `proteinclaw` console script declared in
`pyproject.toml` (`proteinclaw.cli:main`) resolves to a real callable.
"""

from proteinclaw.cli.app import main

__all__ = ["main"]
