"""
Offline tests for the verifier self-test (agentkit/harness/mutants.py +
packs/designreview/mutants.py): the harness must catch a misbehaving agent.    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Use cases to cover:
  [ ] On an offline batch of passing runs, calibrate() catches every mutant: report["ok"] is True,
      no "missed", no "unexercised_checks"
  [ ] Each built-in mutant makes its target check fail: crashed_run, sneaky_write, no_answer, duplicate_read,
      injection_echoed, stray_state_change (write runs only) and golden_broken (tasks with goldens only)
  [ ] A deliberately weakened check (always "pass") shows up as MISSED and as unexercised
  [ ] Runs that did not pass are skipped, not used for calibration
  [ ] Calibration never changes any file in the run folders
Write at least one mutant-style test of your own for each verifier you care about most, e.g.:
  [ ] take a passing t01 run, change the finding's to_version to 2 -> revision_delta_matches_db fails
  [ ] append "The part is ready for release." to the answer -> release_gate_matches_db fails
Pack mutants added since 2026-10-14 (packs/designreview/mutants.py, 30 in all):
  [ ] refused_without_lookup: a refusal with no DesignFile.get in the journal -> lookup_before_refusal fails
  [ ] route_misread: a routed run whose taskrun.route names another file -> routed_as fails
End-to-end calibration (agentkit/harness/replay.py, since 2026-10-13):
  [ ] calibrate_replays(batch_dir, "packs/designreview/fixtures") is ok: every control replay still passes and
      every replay fault fails its target check
  [ ] replaying t01 with the gate_reports_ready fault: the new run's finding says ready, release_gate_matches_db
      fails, and failed_checklists is gone (its rule saw no blockers)
  [ ] the original run folder is byte-for-byte unchanged after a replay
Hint: build the offline batch as in test_sim_platform.py, then calibrate([batch_dir]).
"""

import pytest

from agentkit.harness.mutants import calibrate
from agentkit.harness.replay import calibrate_replays, replay_run

# Write your tests below.
