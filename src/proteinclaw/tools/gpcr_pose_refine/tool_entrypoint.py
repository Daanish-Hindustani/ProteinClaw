"""JSON-file entrypoint for the GPCR pose-transfer/refinement container."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from implementation import run


def main() -> int:
    input_path = Path(os.environ.get("INPUT_FILE", "/workspace/input.json"))
    output_path = Path(os.environ.get("OUTPUT_FILE", "/workspace/output.json"))
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        result = run(**payload)
    except Exception as exc:  # noqa: BLE001
        result = {
            "summary": f"Error: GPCR pose-refinement entrypoint crashed: {exc}",
            "error": "entrypoint_crash",
            "metrics": {},
            "details": {"exception_type": type(exc).__name__},
        }
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
