#!/usr/bin/env python3
"""JSON entrypoint for the ProteinClaw ESMFold image."""

from __future__ import annotations

import json
import os
import sys
import traceback


def main() -> None:
    input_file = os.environ.get("INPUT_FILE", "/work/input.json")
    output_file = os.environ.get("OUTPUT_FILE", "/work/output.json")
    try:
        with open(input_file, encoding="utf-8") as handle:
            args = json.load(handle)
        if not isinstance(args, dict):
            args = {}

        sys.path.insert(0, "/opt")
        from implementation import run

        result = run(**args)
        if not isinstance(result, dict):
            result = {"summary": str(result)}
        with open(output_file, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, default=str)
    except Exception as exc:  # pragma: no cover - exercised inside container
        with open(output_file, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "summary": f"Error: {exc}",
                    "error": traceback.format_exc(),
                },
                handle,
                indent=2,
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
