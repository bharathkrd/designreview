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

  pass@k and pass^k (G3, not built yet):
  [ ] n=3 runs, c=2 pass: pass@1 = 2/3, pass@2 = 1, pass@3 = 1
  [ ] same task: pass^1 = 2/3, pass^2 = 1/3, pass^3 = 0
  [ ] values are exact fractions written as strings ("1/3"), so batch_score.json stays byte-stable
      and grade --check still says "identical"
  [ ] k > n is rejected (or not reported), never a division by zero

  Error bars (G3, not built yet):
  [ ] Wilson 95% interval for 9 of 9 tasks passing is about (0.70, 1.00)
  [ ] Wilson 95% interval for 0 of 20 attacked runs succeeding has an upper bound of about 0.16
  [ ] Clustered standard error (cluster = task) is >= the plain standard error when repeats agree

  Trivial-agent baselines (G2):
  [ ] (works today -- keep it so) a "null agent" bundle (no tool calls, finding declined, answer
      "I can't answer that") fails every one of the nine tasks
  [ ] (works today) a hand-off list naming every possible owner fails handoffs_match_platform (exact set)
  [ ] (gap today) t02's real finding and answer with an EMPTY journal -> record_absent must fail: a refusal
      decided without the one DesignFile.get lookup is not a correct refusal (today it passes)

  Partial credit (G9, not built yet; report only, never a gate):
  [ ] 3 of 4 applicable checks pass -> S_partial = 0.5 * 3/4 + 0.5 * 0 = 0.375
  [ ] all checks pass -> S_partial = 1.0;  "skip" checks are not in the denominator

  Failure modes (G10, not built yet):
  [ ] every registered check and mutant has a failure-mode tag from the allowed set
      (wrong_fact, ignored_evidence, fabrication, policy_breach, premature_stop, verification_gap)
  [ ] report.md counts failed checks by mode

  Tool-call budget (G11, not built yet):
  [ ] a journal with two identical reads (same tool, same args) -> tool_call_budget fails
  [ ] a journal within the plan's maximum -> tool_call_budget passes

Hint: build a manifest by hand: {"batch_id": "b", "repeat": 3, "expected": {"t": 3}, "runs": [...]},
and results as [(entry, {"status": "pass"}), ...] -- then call score_batch(manifest, results).
For check tests, build a RunBundle by hand (see test_verifiers.py) and call the check function directly.
"""

import pytest

from agentkit.harness.checks import BUILTIN_CHECKS, CheckOutcome, RunBundle, check_run
from agentkit.harness.grade import overall_status, score_batch
from packs.designreview.checks import check_release_gate

# Write your tests below.
