#!/usr/bin/env python3
"""Universal container entrypoint shim (PRD §9.2) — identical across tools.

Do not customise. Copy-pasted into every GPU tool directory so that the only
contract between host and container is JSON in via ``$INPUT_FILE``, JSON out
via ``$OUTPUT_FILE``.
"""

from __future__ import annotations

import json
import os
import sys
import traceback


def _read_input(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"input file {path!r} did not contain a JSON object")
    return data


def _write_output(path: str, envelope: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2, default=str)
    os.replace(tmp, path)


def main() -> int:
    input_file = os.environ.get("INPUT_FILE", "/workspace/input.json")
    output_file = os.environ.get("OUTPUT_FILE", "/workspace/output.json")
    session_id = os.environ.get("SESSION_ID", "")
    tool_name = os.environ.get("TOOL_NAME", "unknown")

    try:
        import implementation  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        _write_output(
            output_file,
            {
                "summary": f"Error: could not import implementation.py for {tool_name}: {exc}",
                "error": "implementation_import_failed",
                "metrics": {},
                "session_id": session_id,
            },
        )
        return 1

    try:
        kwargs = _read_input(input_file)
    except Exception as exc:  # noqa: BLE001
        _write_output(
            output_file,
            {
                "summary": f"Error: could not read {input_file}: {exc}",
                "error": "input_read_failed",
                "metrics": {},
                "session_id": session_id,
            },
        )
        return 1

    try:
        result = implementation.run(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _write_output(
            output_file,
            {
                "summary": f"Error: {tool_name} raised {type(exc).__name__}: {exc}",
                "error": "tool_exception",
                "traceback": traceback.format_exc(),
                "metrics": {},
                "session_id": session_id,
            },
        )
        return 1

    if not isinstance(result, dict):
        _write_output(
            output_file,
            {
                "summary": (
                    f"Error: {tool_name}.run() returned non-dict "
                    f"({type(result).__name__})"
                ),
                "error": "bad_result_shape",
                "metrics": {},
                "session_id": session_id,
            },
        )
        return 1

    result.setdefault("session_id", session_id)
    result.setdefault("metrics", {})
    _write_output(output_file, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
