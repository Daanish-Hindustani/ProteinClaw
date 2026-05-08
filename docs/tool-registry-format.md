# Tool Registry Format

Every protein-design tool is a `BaseTool` subclass declaring four class
variables and one async method:

| Field | Source | Notes |
|---|---|---|
| `name` | `ClassVar[str]` | Unique registry key. |
| `description` | `ClassVar[str]` | Surfaced to the LLM via `ToolRegistry.describe_all()`. |
| `input_schema` | `ClassVar[type[BaseModel]]` | Pydantic model; validates raw inputs at the boundary. |
| `output_schema` | `ClassVar[type[BaseModel]]` | Pydantic model; type-checked at the boundary. |
| `examples` | `ClassVar[tuple[ToolExample, ...]]` | Optional input/output pairs. |
| `_execute(inputs) -> BaseModel` | `async` method | Concrete tool logic; returns an instance of `output_schema`. |

The public entry point is `BaseTool.invoke(raw_inputs: dict)` which:

1. Validates `raw_inputs` against `input_schema` (raises `ToolExecutionError` on failure).
2. Awaits `_execute(inputs)`.
3. Verifies the return is an `output_schema` instance.
4. Returns a `ToolOutput(payload=output.model_dump(), metrics={"latency_ms": ...})`.

**Errors are exceptions, never silent.** A failed invocation always
raises `ToolExecutionError`; the registry records it as a `ToolInvocation`
with `status=FAILURE` and re-raises.

## Registered tools

<!-- AUTO-GENERATED:tools (source: src/proteinclaw/tools/protein/*.py) -->

| `name` | Module | Input schema | Output schema | Backends |
|---|---|---|---|---|
| `rcsb` | `tools/protein/rcsb.py` | `RCSBInputs` | `RCSBOutputs` | `mock`, `rest` |
| `rfdiffusion3` | `tools/protein/rfdiffusion3.py` | `RFDiffusionInputs` | `RFDiffusionOutputs` | `mock`, `local` |
| `protein_mpnn` | `tools/protein/protein_mpnn.py` | `ProteinMPNNInputs` | `ProteinMPNNOutputs` | `mock`, `local` |
| `alphafold` | `tools/protein/alphafold.py` | `FoldInputs` | `FoldOutputs` | `mock`, `esm_atlas`, `colabfold` |
| `foldseek` | `tools/protein/foldseek.py` | `FoldseekInputs` | `FoldseekOutputs` | `mock`, `rest` |

<!-- /AUTO-GENERATED:tools -->

## ToolOutput envelope

```python
class ToolOutput(BaseModel):
    tool_name: str
    status: ToolStatus           # SUCCESS | FAILURE
    payload: dict[str, Any]      # output_schema.model_dump()
    stderr: str = ""             # captured stderr (real backends)
    metrics: dict[str, float]    # at minimum {"latency_ms": ...}
```

Frozen Pydantic model. `status=FAILURE` never appears here at runtime —
failures raise `ToolExecutionError`. The field exists for trace
serialization symmetry.

## Adding a new tool

1. Define input + output Pydantic models with `model_config = ConfigDict(frozen=True, extra="forbid")`.
2. **Validate every free-form string field** with a `field_validator` constraining the character set. Tools that interpolate user-supplied strings into CLI args (Hydra-style) are particularly exposed.
3. Define a `Backend` Protocol and at least a `Mock<Tool>Backend`.
4. Implement the `BaseTool` subclass with the four class vars + `_execute`.
5. Add a factory function in `src/proteinclaw/tools/factory.py` and register it in `build_default_registry()`.
6. Document the input/output schema, expected runtime, and any failure modes.
