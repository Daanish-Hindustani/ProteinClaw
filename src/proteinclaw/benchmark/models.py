"""Benchmark domain models.

Benchmarks are intentionally lightweight in v1: a suite is a list of prompts
plus optional execution caps, and a report records the orchestrator's final
payload in a comparable JSON shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from proteinclaw.evaluation.scoring import Verdict


class BenchmarkTask(BaseModel):
    """One prompt-level benchmark task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    prompt: str
    fanout: int | None = Field(default=None, ge=1)
    iterations: int | None = Field(default=None, ge=1)
    tags: tuple[str, ...] = ()

    @field_validator("id", "prompt")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        """Require useful identifiers and prompts."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class BenchmarkSuite(BaseModel):
    """A fixed list of benchmark tasks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    description: str = ""
    tasks: tuple[BenchmarkTask, ...]

    @field_validator("id")
    @classmethod
    def _non_empty_id(cls, value: str) -> str:
        """Require a stable suite id."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("suite id must not be empty")
        return stripped

    @field_validator("tasks")
    @classmethod
    def _unique_task_ids(cls, value: tuple[BenchmarkTask, ...]) -> tuple[BenchmarkTask, ...]:
        """Reject empty suites and duplicate task ids."""
        if not value:
            raise ValueError("suite must contain at least one task")
        ids = [task.id for task in value]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark task ids must be unique")
        return value

    @classmethod
    def from_yaml(cls, path: Path) -> BenchmarkSuite:
        """Load a benchmark suite from YAML."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)


class BenchmarkTaskResult(BaseModel):
    """Result of running one benchmark task through the orchestrator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    prompt: str
    session_id: str
    verdict: str
    winner_branch_id: str | None = None
    metric_scores: tuple[dict[str, Any], ...] = ()
    elapsed_seconds: float = Field(ge=0.0)
    final_task_payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        """True when the task's selected verdict is STOP_SUCCESS."""
        return self.verdict == Verdict.STOP_SUCCESS.value


class BenchmarkReport(BaseModel):
    """Comparable report for one benchmark suite run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    suite_id: str
    suite_description: str = ""
    git_branch: str
    git_commit: str
    backend_mode: str
    verdict_counts: dict[str, int]
    success_rate: float = Field(ge=0.0, le=1.0)
    task_results: tuple[BenchmarkTaskResult, ...]

    @classmethod
    def build(
        cls,
        *,
        suite: BenchmarkSuite,
        git_branch: str,
        git_commit: str,
        backend_mode: str,
        task_results: tuple[BenchmarkTaskResult, ...],
    ) -> BenchmarkReport:
        """Build a report and derive aggregate fields."""
        counts: dict[str, int] = {}
        for result in task_results:
            counts[result.verdict] = counts.get(result.verdict, 0) + 1
        successes = counts.get(Verdict.STOP_SUCCESS.value, 0)
        success_rate = successes / len(task_results) if task_results else 0.0
        return cls(
            suite_id=suite.id,
            suite_description=suite.description,
            git_branch=git_branch,
            git_commit=git_commit,
            backend_mode=backend_mode,
            verdict_counts=counts,
            success_rate=success_rate,
            task_results=task_results,
        )

    @classmethod
    def from_json_file(cls, path: Path) -> BenchmarkReport:
        """Load a report from JSON."""
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def write_json(self, path: Path) -> None:
        """Write this report as pretty JSON, creating the parent directory."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
