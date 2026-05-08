"""Tiny ANSI-colored print helpers shared across the CLI.

No third-party deps; respects `NO_COLOR` and non-TTY stdout.
"""

from __future__ import annotations

import os
import sys

_ANSI = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_GREEN = "\033[32m" if _ANSI else ""
_RED = "\033[31m" if _ANSI else ""
_YELLOW = "\033[33m" if _ANSI else ""
_BLUE = "\033[34m" if _ANSI else ""
_BOLD = "\033[1m" if _ANSI else ""
_DIM = "\033[2m" if _ANSI else ""
_RESET = "\033[0m" if _ANSI else ""


def header(text: str) -> None:
    """Print a bold blue section header."""
    print(f"\n{_BOLD}{_BLUE}== {text} =={_RESET}")


def info(text: str) -> None:
    """Print a neutral info line."""
    print(f"{_BLUE}[info]{_RESET} {text}")


def ok(text: str) -> None:
    """Print a success line."""
    print(f"{_GREEN}[ ok ]{_RESET} {text}")


def warn(text: str) -> None:
    """Print a warning line to stderr."""
    print(f"{_YELLOW}[warn]{_RESET} {text}", file=sys.stderr)


def err(text: str) -> None:
    """Print an error line to stderr."""
    print(f"{_RED}[fail]{_RESET} {text}", file=sys.stderr)


def dim(text: str) -> str:
    """Return `text` wrapped in ANSI dim codes."""
    return f"{_DIM}{text}{_RESET}"


def bold(text: str) -> str:
    """Return `text` wrapped in ANSI bold codes."""
    return f"{_BOLD}{text}{_RESET}"
