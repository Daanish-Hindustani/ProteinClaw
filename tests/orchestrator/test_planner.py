"""Tests for orchestrator/planner.py — heuristic routing, PDB id extraction."""

from __future__ import annotations

import pytest

from proteinclaw.common.types import Metric
from proteinclaw.orchestrator.planner import Planner


@pytest.mark.parametrize(
    ("request_text", "expected_task_type"),
    [
        ("Design a binder for PDB 1ABC", "binder_design"),
        ("Improve enzyme stability", "enzyme_design"),
        ("Stabilize this protein", "enzyme_design"),
        ("Scaffold this motif", "motif_scaffolding"),
        ("Find hotspots on the target", "hotspot_selection"),
        ("Help me with proteins", "binder_design"),  # default fallback
    ],
)
async def test_heuristic_routing(request_text: str, expected_task_type: str) -> None:
    tasks = await Planner().plan(user_request=request_text, session_id="s1")
    assert len(tasks) == 1
    assert tasks[0].inputs["task_type"] == expected_task_type
    assert tasks[0].max_iterations == 3


async def test_binder_task_extracts_pdb_id() -> None:
    tasks = await Planner().plan(user_request="Design a binder for PDB 2XYZ", session_id="s1")
    assert tasks[0].inputs["target_pdb_id"] == "2XYZ"


async def test_binder_task_default_pdb_when_absent() -> None:
    tasks = await Planner().plan(user_request="Design me a small binder please", session_id="s1")
    assert tasks[0].inputs["target_pdb_id"] == "1ABC"


async def test_binder_success_criteria_target_plddt_and_ptm() -> None:
    tasks = await Planner().plan(user_request="Design a binder for 1ABC", session_id="s1")
    metrics = {c.metric for c in tasks[0].success_criteria}
    assert {
        Metric.PLDDT,
        Metric.PTM,
        Metric.BINDER_MONOMER_CONFIDENCE,
        Metric.COMPLEX_CONFIDENCE,
        Metric.INTERFACE_CONTACTS,
        Metric.INTERFACE_SASA,
        Metric.CLASH_SCORE,
        Metric.TARGET_BINDER_MIN_DISTANCE,
    } <= metrics


async def test_hotspot_binder_adds_hotspot_satisfaction_criterion() -> None:
    tasks = await Planner().plan(
        user_request="Design a binder for 1ABC using hotspots A45 and A46",
        session_id="s1",
    )
    metrics = {c.metric for c in tasks[0].success_criteria}
    assert Metric.HOTSPOT_SATISFACTION in metrics
