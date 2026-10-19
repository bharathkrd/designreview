"""
Offline tests for how the harness *reports* results: reliability over repeats, error bars,
trivial-agent baselines, partial credit, failure modes and tool-call budgets
(agentkit/harness/grade.py, agentkit/harness/checks.py, packs/designreview/checks.py).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Background: docs/RESEARCH_GAP_ANALYSIS.md, gaps G2, G3, G9, G10, G11 (and §4 for the math).
Items marked (not built yet) test a feature that does not exist today: write the test, and mark it
@pytest.mark.xfail(strict=True, reason="G#") (or skip) until the feature lands.

Use cases to cover:
  Works today:
  [ ] score_batch: 3 runs of one task, 2 pass -> pass_all is False and the run ids that failed are listed
  [ ] score_batch: a task in manifest["expected"] with no runs counts as missing and does not pass
  [ ] A hedged answer ("The part is ready for release. It is not ready.") against a NOT-ready gate:
      release_gate_matches_db must fail -- an answer that lists both verdicts can't pass (G2)

  pass@k and pass^k (G3, built 2026-10-14: grade.pass_at_k / pass_hat_k / frac, score_batch rows):
  [ ] n=3 runs, c=2 pass: pass@1 = 2/3, pass@2 = 1, pass@3 = 1
  [ ] same task: pass^1 = 2/3, pass^2 = 1/3, pass^3 = 0
  [ ] values are exact fractions written as strings ("1/3"), so batch_score.json stays byte-stable
      and grade --check still says "identical"
  [ ] k > n is rejected (or not reported), never a division by zero

  Error bars (G3, built 2026-10-14: grade.wilson_interval / clustered_se, batch_score.json "total"):
  [ ] Wilson 95% interval for 9 of 9 tasks passing is about (0.70, 1.00)
  [ ] Wilson 95% interval for 0 of 20 attacked runs succeeding has an upper bound of about 0.16
  [ ] Clustered standard error (cluster = task) is >= the plain standard error when repeats agree

  Trivial-agent baselines (G2):
  [ ] (works today -- keep it so) a "null agent" bundle (no tool calls, finding declined, answer
      "I can't answer that") fails every one of the twelve tasks
  [ ] (works today) a hand-off list naming every possible owner fails handoffs_match_platform (exact set)
  [ ] lookup_before_refusal (added 2026-10-14): a journal whose DesignFile.get for the id ended
      error_kind "missing" -> pass; an empty journal -> fail; a flaky try then a "missing" retry -> pass

  Partial credit (G9, built 2026-10-14: grade.partial_score, score.json "partial"; report only):
  [ ] 3 of 4 applicable checks pass -> S_partial = 0.5 * 3/4 + 0.5 * 0 = 0.375
  [ ] all checks pass -> S_partial = 1.0;  "skip" checks are not in the denominator

  Failure modes (G10, built 2026-10-14: registry.FAILURE_MODES, checks.failure_mode_of):
  [ ] every built-in and pack check has a failure mode from FAILURE_MODES
  [ ] Registry().check("x", failure_mode="bad_luck") raises ValueError
  [ ] a failed check shows up in score.json "fail_modes" under its mode; report.md counts failed checks by mode

  Tool-call budget (G11, built 2026-10-14: checks.check_tool_call_budget, mutant duplicate_read):
  [ ] a journal with two identical successful reads (same tool, same args) -> tool_call_budget fails
  [ ] the same read again AFTER a write -> passes (the state may have changed)
  [ ] a failed read retried with the same args -> passes
  [ ] in a replay (replay.json has replay_start_seq) only calls from that seq on are counted

  Cost against accuracy (G12, built 2026-10-15: agentkit/harness/pareto.py, docs/COST_ACCURACY.md):
  [ ] load_arm on a hand-made batch: runs, passed, cost, cost per pass, escalations (runs with calls on more
      than one model) and answer sources come out as built
  [ ] a run with no score.json counts as not passed
  [ ] frontier(): an arm with a higher pass rate and a lower cost beats another; two equal arms are both on it
  [ ] a template-only arm (manifest skip_llm = true) is labelled "template only (no LLM)" and costs 0

More use cases (added 2026-10-16, to write by hand):
  [ ] pass_at_k(3, 2, 4) and pass_hat_k(3, 2, 0) raise ValueError (k must be 1..n)
  [ ] wilson_interval(0, 0) is (0.0, 1.0): no runs means no knowledge, not an error
  [ ] partial_score(0, 0, full=True) == 1 and partial_score(0, 0, full=False) == 0 (no applicable checks)
Hint: build a manifest by hand: {"batch_id": "b", "repeat": 3, "expected": {"t": 3}, "runs": [...]},
and results as [(entry, {"status": "pass"}), ...] -- then call score_batch(manifest, results).
For check tests, build a RunBundle by hand (see test_verifiers.py) and call the check function directly.
"""

import pytest

from agentkit.harness.checks import BUILTIN_CHECKS, CheckOutcome, RunBundle, check_run, check_tool_call_budget
from agentkit.harness.grade import (clustered_se, frac, overall_status, partial_score, pass_at_k, pass_hat_k,
                                    score_batch, wilson_interval)
from agentkit.registry import FAILURE_MODES, Registry
from packs.designreview.checks import check_lookup_before_refusal, check_release_gate

# Write your tests below.
