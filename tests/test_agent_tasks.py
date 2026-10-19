"""
End-to-end agent tasks, verified against the DATABASE, not the agent's prose.
Markers: agent + live (module-wide). Costs LLM calls, so run sparingly.

Author(s): Sunil Jakkaraju    Written by hand: [yes] 

The tasks are data: packs/designreview/tasks/*.toml. Run one with
agentkit.harness.run_one.run_task(task, "suryodaya", tmp_path, "id") and assert on the
returned TaskRun (finding + claimed_answer) and the saved run folder.

Tasks to cover:
  [ ] t01 Battery Tray rev B -> rev C: finding maps B=v2, C=v3; answer cites 2.0 -> 3.0 mm and 4.2 mm;
      release gate NOT ready with 1 critical open; answer_source is "llm" and its audit is clean
  [ ] t02 unknown file: finding outcome "declined"; tool_journal.jsonl shows only DesignFile.get
  [ ] t03 AI review requested: declined because endpoint.designreview.ai_review is not in the seat;
      that tool never appears in tool_journal.jsonl
  [ ] t04 Bench Vice rev 2 -> rev 3: numeric revs mapped; answer mentions the 180 g saving;
      no sentence claims a geometry comparison
  [ ] t05 Propeller: rev B = v1 and rev C = v2 (mapped by commit note, not by position)
  [ ] Every run: taskrun.json existed with ended="running" before the plan ran (read it from a
      patched plan step, or check graph.json + taskrun.json timestamps)
  [ ] Keystone: the same question on a Keystone file answers from Keystone data (mark keystone)
More use cases (added 2026-10-16, to write by hand):
  [ ] t08 Battery Tray hand-off (dry run): file_handoffs ends HANDED_OFF with filed False, and
      tool_journal.jsonl has no AgentEscalation.create and no escalations.raise
  [ ] t11 "Is the propeller ready for release?": route.plan is "route_declined", route.params.reason names
      "4 design files", and the journal has no release-readiness call (no guess was made)
  [ ] t12 (keystone) auger drive housing cover: route.plan is "release_handoff" and finding.schedule.past_due
      is exactly "DFM Review Complete", "Tooling Kickoff", "First Article Inspection"
Hint: the offline twin of every task is `python -m agentkit.harness.batch --sim
packs/designreview/fixtures/suryodaya.json --skip-llm --grade` -- use it to check your
expectations for free before spending LLM calls here.
"""

import pytest

from agentkit.harness.run_one import run_task
from agentkit.harness.tasks import load_task
from agentkit.record.durable_io import read_jsonl

pytestmark = [pytest.mark.agent, pytest.mark.live]

# Write your tests below.
'''[ ] t01 Battery Tray rev B -> rev C: finding maps B=v2, C=v3; answer cites 2.0 -> 3.0 mm and 4.2 mm;
      release gate NOT ready with 1 critical open; answer_source is "llm" and its audit is clean
''' 
def test_t01_battery_tray(tmp_path):
    task = load_task("packs/designreview/tasks/t01_battery_tray_rev_diff.toml")
    run = run_task(task, "suryodaya", tmp_path, "t01")

    # finding maps B=v2, C=v3
    assert run.finding["revision_delta"]["from_version"] == 2
    assert run.finding["revision_delta"]["to_version"] == 3

    # release gate NOT ready with 1 critical open
    assert run.finding["release_gate"]["ready"] is False
    assert run.finding["release_gate"]["critical_open"] == 1

    # answer cites 2.0 -> 3.0 mm and 4.2 mm
    assert "2.0" in run.claimed_answer
    assert "3.0" in run.claimed_answer
    assert "4.2" in run.claimed_answer

    # answer_source is "llm" and its audit is clean
    assert run.answer_source == "llm"
    narrate_step = next(s for s in run.steps if s.kind == "narrate")
    assert narrate_step.detail["audit"]["ok"] is True


'''[ ] t02 unknown file: finding outcome "declined"; tool_journal.jsonl shows only DesignFile.get
'''

def test_t02_unknown_file(tmp_path):
    task = load_task("packs/designreview/tasks/t02_unknown_file_refusal.toml")
    run = run_task(task, "suryodaya", tmp_path, "t02")

    # finding outcome "declined"
    assert run.finding["outcome"] == "declined"

    # tool_journal shows only DesignFile.get
    journal = read_jsonl(tmp_path / "tool_journal.jsonl")
    assert len(journal) >= 1
    assert all(e.get("tool") == "DesignFile.get" for e in journal)

''' [ ] t03 AI review requested: declined because endpoint.designreview.ai_review is not in the seat;
      that tool never appears in tool_journal.jsonl
'''


''' [ ] t04 Bench Vice rev 2 -> rev 3: numeric revs mapped; answer mentions the 180 g saving;
      no sentence claims a geometry comparison
'''


''' [ ] t05 Propeller: rev B = v1 and rev C = v2 (mapped by commit note, not by position)
'''


''' [ ] Every run: taskrun.json existed with ended="running" before the plan ran (read it from a
      patched plan step, or check graph.json + taskrun.json timestamps)
'''
