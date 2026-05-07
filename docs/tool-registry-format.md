# Tool Registry Format

> Stub. Authored in Phase 2.

Each tool exposes:

- `name` — unique identifier.
- `description` — what it does, when to use it.
- `input_schema` — Pydantic model.
- `output_schema` — Pydantic model.
- `examples` — at least one input/output pair.
- `run(input) -> ToolOutput` — async invocation.

`ToolOutput` carries `status`, `payload`, `stderr`, and `metrics` (latency, cost). Failures raise `ToolExecutionError` and emit a `tool.failed` TraceEvent — never silent.
