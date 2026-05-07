# Project Goals
Build a custom agentic workflow for protein design that can reason through complex design tasks, branch into multiple solution paths, evaluate results, learn from failures, and improve its tools/skills over time.

# Components

## Orchestrator
### Purpose
- The orchestrator is the main controller of the workflow.

### Responsibilities
1. Understand the user’s protein design goal.
2. Decide whether the request is possible with the available tools.
3. Ask follow-up questions when the task is underspecified.
4. Break the request into smaller tasks.
5. Send each task to the Sub-Agent Branching Service.
6. Receive overall results from sub-agents.
7. Send results to the Evaluator.
8. Use evaluator feedback to decide whether to iterate.
9. Stop after at most k iterations per task.
10. Return the final result to the user with reasoning, files, and tool outputs.

## SubAgnets
### Purpose
- Runs multiple sub-agents across different exploration paths for each task.

### Responsibilities
1. Take a task from the orchestrator.
2. Understand the deliverables and success criteria.
3. Select the best tools and skills for the task.
4. Use the Python sandbox for analysis when needed.
5. Call protein design tools such as RFdiffusion, ProteinMPNN, AlphaFold, Foldseek, etc.
6. Spawn child sub-agents when deeper exploration is useful.
7. Explore different branches of reasoning or parameter choices.
8. Backtrack from failed branches.
9. Return the best result from each branch.
10. Save useful reasoning traces for future learning.
11. Leverage the self evolution service to update skills

## Tool registery
### Purpose
Central place where all available tools are listed, described, and invoked.

### Responsibilities
1. Store tool names, descriptions, schemas, and usage examples.
2. Help agents choose the correct tool.
3. Track tool inputs, outputs, errors, and performance.
4. Support tools such as:
    - RFdiffusion3
    - ProteinMPNN
    - AlphaFold / ESMFold
    - PDB / RCSB search
    - Literature search
    - Python sandbox
    - Web search
    - Literature search

## Skill Library
### Purpose
Stores reusable workflows and domain-specific instructions.

### Responsibilities
1. Hold all protein design skills.
2. List available skills for agents.
3. Provide step-by-step workflows for common tasks.
4. Store examples of successful tool usage.
5. Support skills such as:
    - Binder design
    - Enzyme design
    - Motif scaffolding
    - Hotspot selection
    - Contig construction
    - Structure validation
    - Binding/interface evaluation
    
## Evaltator
### Purpose
Scores and critiques agent outputs.

### Responsibilities
1. Evaluate the result of an end-to-end workflow.
2. Check whether the output satisfies the original task.
3. Score tool outputs and design candidates.
4. Identify missing steps, weak reasoning, or bad parameters.
5. Give feedback to the orchestrator or sub-agents.
6. Recommend whether to retry, branch further, or stop.
7. Save evaluation results into memory.

## Evolution service 
### Purpose
Improves the system based on workflow feedback.

### Responsibilities
1. Read evaluator feedback and failed traces.
2. Update existing skills.
3. Create new skills when repeated workflows appear.
4. Improve tool descriptions and usage instructions.
5. Store common mistakes in memory.
6. Improve future planning, branching, and parameter selection.

## Memory System
### Purpose
Stores knowledge from previous runs so the agent improves over time.

### Responsibilities
1. Knowledge Store
    - Stores protein design knowledge, papers, notes, tool docs, and domain concepts.
2. Session Store
    - Stores current run information, task state, intermediate results, and active branches.
3. Trace Store
    - Stores reasoning traces, tool calls, branch decisions, failures, and final outcomes.
4. Compacts memory/context


# WorkFlow
## 1. User Request Intake
    The user submits a protein design request.

    Examples:

    Design a binder for a target protein
    Improve enzyme stability
    Scaffold a motif
    Design a protein around a hotspot region

    The orchestrator:

    Parses the request.
    Determines whether enough information exists.
    Asks follow-up questions if needed.
    Defines success criteria and constraints.

## 2. Task Planning

    The orchestrator decomposes the request into smaller tasks.

    Example binder workflow:

    Retrieve target structure
    Analyze target surface
    Identify hotspots
    Generate contigs
    Generate candidate backbones
    Sequence design
    Structure prediction
    Binding/interface evaluation
    Ranking and filtering

    Each task is sent independently into the Sub-Agent Branching Service.

## 3. Sub-Agent Branch Exploration

    Each task spawns multiple sub-agents that explore different reasoning paths.

    Examples:
    Different hotspot selections
    Different contig strategies
    Different RFdiffusion parameters
    Different sequence generation approaches
    Different ranking heuristics

    Each branch:
    Uses tools
    Uses skills
    Can spawn child sub-agents
    Stores reasoning traces
    Backtracks from failed paths

    The goal is exploration rather than single-path execution.

## 4. Tool + Skill Execution

    Sub-agents dynamically select:

    Tools from the Tool Registry
    Skills from the Skill Library

    Example:

    Use RFdiffusion3 for backbone generation
    Use ProteinMPNN for sequence generation
    Use AlphaFold for structure prediction
    Use Foldseek for structural similarity
    Use literature search for known motifs

    Agents may also:
    Write Python scripts
    Run analyses
    Parse PDBs
    Compute RMSD/interface metrics
    Visualize structures  

## 5. Evaluation Phase
    Results from all branches are sent to the Evaluator.

    The evaluator:

    Scores candidates
    Detects weak reasoning
    Detects parameter failures
    Compares branch performance
    Identifies promising exploration directions

    Evaluation signals may include:

    Predicted confidence
    Interface quality
    RMSD
    Clash scores
    Binding metrics
    Structural novelty
    Constraint satisfaction

## 6. Iteration Loop
    The orchestrator uses evaluator feedback to:

    Retry failed tasks
    Refine parameters
    Spawn new exploration branches
    Stop low-performing branches
    Continue promising paths

    This loop continues until:
    Success criteria are met
    Maximum iteration count is reached(default to max=3)
    Search space converges

## 7. Memory + Trace Storage
    After completion:
    Successful workflows are stored
    Failed workflows are stored
    Tool usage is tracked
    Reasoning traces are compressed
    High-value traces are saved for future learning

    This enables future agents to:

    Reuse successful strategies
    Avoid repeated mistakes
    Improve planning over time

    Session storage is activly added to throughout the workflow

## 8. Self-Evolution
    The Evolution Service analyzes traces and evaluator feedback to improve the system.

    Possible improvements:

    Create new reusable skills
    Refine tool instructions
    Improve parameter defaults
    Generate better planning heuristics
    Improve branching strategies

    Over time the system becomes more specialized for protein design workflows.

    Pls leverage https://gepa-ai.github.io/gepa/blog/2026/02/18/introducing-optimize-anything/
    for the self evolution