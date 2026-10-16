"""
Offline tests for golden values: exact answers a person checked once in the seed data, written as [[golden]]
blocks in the task files and checked on every run (agentkit/harness/goldens.py, the built-in check "golden",
the mutant "golden_broken", scripts/make_goldens.py).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Background: docs/explainers/agentkit_harness.md ("Golden values"); docs/CHANGES.md, 2026-10-16. The feature
exists today.

Use cases to cover:
  The format (GoldenSpec):
  [ ] a block with no comparison, or with two (equals and length), is rejected
  [ ] equals = false and length = 0 count as given (not as "missing")
  [ ] a path that does not start with finding / route / tools / answer is rejected
  [ ] answer_contains with a path is rejected; field with equals is rejected
  [ ] a note that still starts with "CHECK:" is rejected (an unchecked golden cannot be committed)
  [ ] TaskDef(...).to_dict() keeps only the fields that were written, and TaskDef(**d) loads it back

  Paths (resolve):
  [ ] "finding.revision_delta.versions[2].rev" and "...versions[rev=C].version_number" find the same item
  [ ] an index past the end, an unknown key and a selector that matches nothing give "missing"

  Comparisons (compare):
  [ ] equals: 3 == 3 holds; false does not equal 0
  [ ] values with field: [{"text": "2.0 mm"}, {"text": "3.0 mm"}] holds for ["3.0 mm", "2.0 mm"]; an extra item
      fails and the message names it
  [ ] only: ["DesignFile.get", "DesignFile.get"] holds for only = ["DesignFile.get"]; another tool fails
  [ ] answer_contains is case-insensitive; a missing text fails and is named
  [ ] each failure message has the expected and the observed value

  The check and the mutant:
  [ ] a task without goldens gives one "skip"; a task with two goldens gives two outcomes
  [ ] two goldens on the same path give two different outcome names
  [ ] the mutant "golden_broken" makes a passing golden fail, for a finding path, a route path, "tools" and
      answer_contains; it gives None for a task with no goldens

  The helper:
  [ ] scripts/make_goldens.py prints blocks that tomllib can parse; each has note = "CHECK: ..."

Hint: build a RunBundle(run_dir=Path("."), task={"golden": [...]}, taskrun={...}, graph=None, journal=[...],
before={}, after={}) and call agentkit.harness.checks.check_golden(bundle, {}). The mutant is
next(m for m in agentkit.harness.mutants.BUILTIN_MUTANTS if m.name == "golden_broken"); call m.apply(bundle).
"""

import pytest

from agentkit.harness.checks import RunBundle, check_golden
from agentkit.harness.goldens import GoldenSpec, compare, resolve, view
from agentkit.harness.mutants import BUILTIN_MUTANTS
from agentkit.harness.tasks import TaskDef

# Write your tests below.
