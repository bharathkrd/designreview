"""
Offline tests for the official harness runner with our agent inside: harness/runner.py (--sim / --fault /
--out), harness/agent_tasks.py (one results.json entry per task and per check) and
scripts/check_results_json.py (the Release 8.1 results.json rules).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Background: README.md ("Evaluated checks"); docs/CHANGES.md, 2026-10-16; the admin's harness reviews (an
exception must be a failed check with its line; only tasks that ran belong in results.json). All of this
exists today.

Use cases to cover:
  Entries (agent_tasks.entries_for, with hand-made graded results -- no batch needed):
  [ ] one passing task with 3 checks -> 1 task entry + 3 check entries; ids "task:<id>" and
      "check:<id>:<check>:<name>"
  [ ] a check with status "skip" gets no entry (only what ran is reported)
  [ ] a check with status "fail", "error" or "drift" -> passed false, and the evidence starts with the status
  [ ] a failed task's score is its partial credit (score.json "partial"); its evidence names the failed checks
  [ ] a run with no score.json -> a failed task entry that says it was not graded
  [ ] with little room (room=4): every task entry is kept, then the failed checks, then the passing ones

  Errors (agent_tasks.run_agent_tasks):
  [ ] run_batch raising ValueError("x") -> exactly one failed entry "<instance>:agent_tasks", whose evidence
      has "ValueError: x" and "(at <file>:<line>)" -- never a lost result, never a pass
  [ ] an instance that no task lists -> one failed entry that says so

  The runner offline (python -m harness.runner --instance <i> --sim packs/designreview/fixtures --out <f>):
  [ ] keystone: exit 0; results.json has the 4 agent tasks and their checks, all passed
  [ ] with --fault "fail_always:endpoint.designreview.release_readiness:flaky" on suryodaya: exit 1, and the
      failed entries include check:...:release_gate_matches_db:ready with "agent None, platform False"
  [ ] --sim skips the platform smoke checks and needs no login and no network (AGENTKIT_OFFLINE=1)

  The validator (scripts/check_results_json.py: problems(data, instance, min_agent_tasks, expect)):
  [ ] a valid file -> no problems; main([...]) returns 0
  [ ] "passed": "true" (a string), score 1.5, score True, a duplicate id, 0 or 201 entries -> one problem each
  [ ] a failed entry with empty evidence -> a problem; a passed entry with score 0.5 -> a problem
  [ ] --instance suryodaya and an id "keystone:x" -> a problem
  [ ] --expect some-fail on an all-pass file -> a problem (a planted fault was not reported)

Hint: harness/ is a package: `from harness.agent_tasks import entries_for, run_agent_tasks`. Pass
run_agent_tasks a small recorder function(task_id, title, passed, evidence, score=None) that appends to a
list. scripts/ is not a package: load check_results_json.py with importlib.util.spec_from_file_location.
For the runner itself, use subprocess.run([sys.executable, "-m", "harness.runner", ...]) with
AGENTKIT_OFFLINE=1 in the environment and --out in tmp_path.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.agent_tasks import entries_for, run_agent_tasks

# Write your tests below.
