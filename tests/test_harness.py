"""
Offline tests for the run record and the harness grader (raw run first, grade later).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Use cases to cover:
  [ ] TaskRun.open_in(run_dir) writes taskrun.json with ended="running" BEFORE any work
  [ ] A saved run loads back with the same task_id, prompt, steps, finding and claimed_answer
  [ ] A run that crashed after open_in() still has a record, and grades as "fail" (run_completed)
  [ ] add_step records kind / target / ok / detail (and status / error_kind) in order
  [ ] tool_calls_policy fails a dry run whose tool_journal.jsonl shows a write tool
  [ ] tool_calls_policy fails a write run that called a tool outside RunBundle.write_tools, passes one inside it
  [ ] run_task(..., write=True) stays a dry run unless the task sets allow_writes = true
  [ ] batch --write refuses --sim; --keep-writes needs --write
  [ ] Grading the same saved run folder twice gives identical score.json (deterministic)
  [ ] overall_status: any fail/error -> fail; only drift -> drift; else pass
  [ ] agentkit.clock.now_utc() returns AGENTKIT_FROZEN_NOW when set; a value with no timezone raises ValueError
  [ ] frozen_now(iso) pins the clock inside the block and restores it afterwards
  [ ] run_batch(..., batch_id="ci") refuses a second batch with the same id; "../x" is rejected
  [ ] run_batch(..., repeat=2) gives run ids ending -r1 / -r2 and manifest expected_runs == tasks x tenants x 2
  [ ] score_batch(): a task with one failed (or missing) repeat has pass_all False
  [ ] report.md carries "**P of T tasks pass on every run.**"
  [ ] rescore_check(batch_dir) is (True, []) right after grading, and reports a hand-edited score.json
  [ ] run_task creates an empty tool_journal.jsonl even when the run makes no tool call
Hint: use pytest's tmp_path as the run folder; write taskrun.json / tool_journal.jsonl /
ground_truth_after.json yourself, then call agentkit.harness.grade.grade_run(tmp_path).
For batch-level cases, run the offline batch: SimSession("packs/designreview/fixtures", [], reg.read_only)
-> run_batch(tasks, runs_dir=tmp_path, reader_factory=sim.reader_for, agent_runner=sim.run_agent,
fresh_reader_per_task=True, skip_llm=True, batch_id=..., repeat=...) -> grade_batch(batch_dir).
"""

import pytest

from agentkit.harness.grade import grade_run, overall_status
from core.harness import Step, TaskRun

# Write your tests below.
