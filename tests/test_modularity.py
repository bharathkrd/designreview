"""
Architecture guards: the framework stays domain-free and no agent framework
sneaks in.    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Use cases to cover:
  [ ] No file under agentkit/ mentions a design-review name: "designreview", "DesignFile",
      "DesignVersion", "release_readiness", a Battery Tray id ... (agentkit must stay domain-free)
  [ ] No file under agentkit/ imports from packs/
  [ ] requirements.txt names no agent or workflow framework (keep your banned-package list in the test;
      the course brief names the frameworks that are not allowed)
  [ ] No .py file under agentkit/ or packs/ imports any of those packages
  [ ] A second, tiny pack (actions + one plan + one task, written in tmp_path) runs through
      agentkit.harness.run_one.run_task with ZERO changes to agentkit/ -- proof the framework is reusable
  [ ] No config/plan/task file is YAML any more (config/, packs/)
  [ ] The generic modules added since 2026-10-14 name no design-review word either: agentkit/agents/router.py,
      agentkit/answer/quarantine.py, agentkit/harness/goldens.py, agentkit/harness/pareto.py,
      agentkit/retrieval/quality.py
Hint: walk Path("agentkit").rglob("*.py") and read the text; parse imports with the `ast` module
rather than grepping, so comments and docstrings don't cause false alarms.
"""

import ast
from pathlib import Path

import pytest

# Write your tests below.
