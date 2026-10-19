"""
Offline tests for choosing what to do: from the question to a plan and a part, the guard on any
planner's patches, fallback rules when a node fails, and checking tool arguments before a call
(agentkit/graph/*, agentkit/transport/*, packs/designreview/plans/*).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Background: docs/RESEARCH_GAP_ANALYSIS.md, gaps G1, I6, I7, I9.
Items marked (not built yet) test a feature that does not exist today: write the test, and mark it
@pytest.mark.xfail(strict=True, reason="G#/I#") (or skip) until the feature lands.

Use cases to cover:
  Works today (the guard every planner must pass):
  [ ] a GraphPatch naming an action the pack did not register -> ValueError, graph unchanged
  [ ] a patch that would create a cycle, or pass the node budget -> ValueError, graph unchanged
  [ ] the rev_diff_dfm rule adds failed_checklists only when the gate reports blockers

  Question -> plan and part (G1, I6a, built 2026-10-14: agentkit.agents.router.RuleRouter,
  packs/designreview/router.py and routes.toml; the LLM-planner line is still not built):
  [ ] "Run the platform's AI design review on the Battery Tray" -> plan tool_refusal
  [ ] "What changed between rev B and rev C on the Battery Tray?" -> plan rev_diff_dfm
  [ ] "battery tray" resolves to the Battery Tray file id on the Suryodaya fixture
  [ ] a name that matches two files -> decline (or ask), never a guess
  [ ] "the propeller" on the Suryodaya fixture -> declined, and the reason names the four candidate files
  [ ] a question with a UUID in it uses that id and reads no file list
  [ ] department words that many file names share ("Quality", "Despatch") are not evidence of a match
  [ ] a task file with only a prompt (no plan, no file_id) runs and grades like t01
  [ ] (not built yet) an LLM planner's patch is checked exactly like a rule's: a raw tool name is refused

  Fallback rules (I7, built 2026-10-15: WhenModel verdict = "failed"; rev_diff_dfm rule
  failed_checklists_when_gate_unreadable):
  [ ] fail_always on the release gate -> the plan's fallback rule adds failed_checklists (added_by "planner",
      requires "settled"), and the node resolves
  [ ] the run still grades "fail" on release_gate_matches_db and on the golden release_gate.ready: nothing
      takes the place of the gate's verdict

  Argument checks (I9, built 2026-10-14: transport.journal.argument_problems, JournaledSeatClient):
  [ ] a call missing a required argument (per the tool's inputSchema) is refused before it is sent,
      and the journal records no send
  [ ] a call with all required arguments goes through unchanged

More use cases (added 2026-10-16, to write by hand):
  [ ] a question that matches no route -> route_declined with a reason, never a default plan
  [ ] Route.matches is case-insensitive: "WHAT CHANGED between rev B and rev C" matches like the lower-case text
  [ ] RouteDecision.declined is True only for the decline plan
Hint: GraphStore + LiveGraphExecutor run a plan with any object that has invoke_tool(name, args) and
offers(name); a SimPlatform on packs/designreview/fixtures/suryodaya.json is one. ToolCatalog gives each
tool's inputSchema and required arguments.
"""

import pytest

from agentkit.graph import GraphPatch, GraphStore, LiveGraphExecutor, RulePlanner, RunEnv, load_plan
from agentkit.registry import load_pack
from agentkit.sim import SimPlatform
from agentkit.transport.catalog import ToolCatalog

# Write your tests below.
