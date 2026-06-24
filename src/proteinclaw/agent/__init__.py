"""Agent core — wires the Hermes harness to the ProteinClaw workflow.

Public surface kept narrow on purpose. See PRD §6.3 + §9.1 for the spec
this implements.
"""

from proteinclaw.agent.core import RunPaths, run_campaign
from proteinclaw.agent.skills import load_skill_text
from proteinclaw.agent.trace import TraceWriter

__all__ = ["RunPaths", "TraceWriter", "load_skill_text", "run_campaign"]
