# AGENT.md

# PROJECT OVERVIEW

Build a custom agentic workflow for protein design that can reason through complex design tasks, branch into multiple solution paths, evaluate results, learn from failures, and improve its tools/skills over time.

The system should support:
- Orchestrated task planning
- Branching sub-agent exploration
- Protein design tool execution
- Evaluation and scoring
- Memory and trace storage
- Self-evolution of skills, prompts, and tool descriptions

# BACKGROUD/WORKFLOW
see ./PROJECT.md

# CORE PRINCIPLES

1. Keep the code modular.
2. Do not cram unrelated logic into the same file.
3. Use clean classes and abstractions.
4. Write high-quality comments where they add clarity.
5. Add docstrings to every public function, method, and class.
6. Document important design decisions.
7. Keep tests meaningful and maintain at least 80% test coverage.
8. Consult the user before implementing large components or changing architecture.
9. Prefer simple, readable implementations over clever abstractions.
10. Every major workflow should be traceable and debuggable.

# CODE FORMAT

## Comments

- Add quality comments for non-obvious logic.
- Do not add useless comments that simply repeat the code.
- Explain why something is done, not just what it does.

## Docstrings

Every class and function must include a docstring.

Example:

```python
class Orchestrator:
    """
    Coordinates user requests, task planning, sub-agent execution,
    evaluation, iteration, and final response generation.
    """
    def plan_tasks(request: str) -> list[Task]:
        """
        Convert a user protein design request into a list of executable tasks.

        Args:
            request: The raw user request.

        Returns:
            A list of structured Task objects.
        """
```

# FOLDER STRUTURE
```bash
src/
  orchestrator/
    orchestrator.py
    planner.py
    task.py

  agents/
    sub_agent.py
    branching_service.py
    branch_result.py

  tools/
    registry.py
    base_tool.py
    protein/
      rfdiffusion3.py
      protein_mpnn.py
      alphafold.py
      foldseek.py
      rcsb.py

  skills/
    skill.py
    skill_library.py
    protein_design/
      binder_design.md
      enzyme_design.md
      motif_scaffolding.md
      hotspot_selection.md

  evaluation/
    evaluator.py
    metrics.py
    scoring.py

  memory/
    memory_manager.py
    knowledge_store.py
    session_store.py
    trace_store.py
    compaction.py

  evolution/
    evolution_service.py
    skill_writer.py
    mistake_tracker.py

  sandbox/
    python_runner.py

tests/
  orchestrator/
  agents/
  tools/
  skills/
  evaluation/
  memory/
  evolution/

```

# DOCUMENTAION
    Document everything important.

    Required documentation:

    Project overview
    Architecture
    Workflow
    Tool registry format
    Skill format
    Memory format
    Trace format
    Evaluation metrics
    Setup instructions
    Testing instructions
    Examples

# TESTING
    Maintain at least 80% test coverage.
    Write tests for all major components.
    Tests should validate behavior, not just implementation details.
    Add unit tests for small logic.
    Add integration tests for workflows.
    Add regression tests for fixed bugs.
    Mock expensive protein design tools in normal CI.
    Use fixture data for PDBs, tool outputs, and evaluator outputs.


# QUALITY BAR

    Code is not complete unless:

    It is modular.
    It is documented.
    It has meaningful tests.
    It has clear abstractions.
    It can be debugged through traces.
    It does not hide failures.
    It does not silently skip failed tools.
    It follows the agreed architecture.