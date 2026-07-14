#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import traceback


def main() -> int:
    input_path = os.environ.get("INPUT_FILE", "/workspace/input.json")
    output_path = os.environ.get("OUTPUT_FILE", "/workspace/output.json")
    session_id = os.environ.get("SESSION_ID", "")
    try:
        with open(input_path, encoding="utf-8") as handle:
            args = json.load(handle)
        import implementation

        result = implementation.run(**args)
        result.setdefault("session_id", session_id)
        result.setdefault("metrics", {})
    except Exception as exc:  # noqa: BLE001
        result = {
            "summary": f"Error: Boltz-2 GPCR wrapper raised {type(exc).__name__}: {exc}",
            "error": "tool_exception",
            "traceback": traceback.format_exc(),
            "metrics": {},
            "session_id": session_id,
        }
    tmp = output_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, default=str)
    os.replace(tmp, output_path)
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
