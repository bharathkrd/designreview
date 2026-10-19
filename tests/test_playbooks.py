"""
Offline tests for the playbooks: one file per use case, with a status the check proves against the
plans, the routes, the tasks and the captured seat tool lists; and the constants register
(agentkit/playbooks.py, scripts/playbooks_check.py, packs/designreview/playbooks/).
Markers: none

Author(s): ____________    Written by hand: [ ] yes

Background: packs/designreview/playbooks/README.md; docs/CHANGES.md, 2026-10-19.

Use cases to cover:
  The pack's own files:
  [ ] check_playbooks(...) on the pack's playbooks returns no problem
  [ ] every task in packs/designreview/tasks belongs to exactly one playbook
  [ ] the README index equals index_table(...) (with_index(readme, books) == readme)

  Each status is a claim the check proves (copy a playbook with model_copy(update=...) and plant one mistake):
  [ ] a live playbook whose plan does not exist -> "is not in the pack's plans"
  [ ] a live playbook whose question routes to another plan -> "routes to ..."
  [ ] a tool that one seat does not offer -> "not offered to every seat"
  [ ] a blocked playbook whose missing_tools names a tool a seat offers -> "listed missing but offered"
  [ ] a blocked playbook with an empty blocked_by -> "does not say why"
  [ ] a spec playbook whose question routes to a live plan -> "expected route_declined"
  [ ] a trigger that is not on_request, scheduled:<cadence> or event:<name>
  [ ] a playbook removed -> its tasks and its plan "belong to no playbook"

  Reading the files:
  [ ] split_front_matter: a +++ head and a body; a file with no head gives ({}, text)
  [ ] an unknown field or an unknown status in a head -> ConfigError naming it

  Constants:
  [ ] check_constants on packs/designreview/playbooks/constants.toml returns no problem
  [ ] a register value changed in memory (0.25 -> 0.5) -> "register says 0.5"
  [ ] read_where for the three forms: "file.toml#key", "module:NAME", "module:Callable(param)"

  Safety (built 2026-10-19):
  [ ] endpoint.designreview.release_impact and supplier_response_sla are not in the registry's read_only set;
      release_impact.get is

Hint: reg = load_pack("packs.designreview"); x = reg.extras; books = load_playbooks(x["playbooks_dir"]);
tasks = {p.stem: read_config(p) for p in Path(x["tasks_dir"]).glob("*.toml")};
catalogs = {p.stem: set(json.loads(p.read_text(encoding="utf-8"))["tools"]) for p in Path(x["fixtures_dir"]).glob("*.json")};
check_playbooks(books, plans=[...], tasks=tasks, catalogs=catalogs, router=x["router"]).
"""

import json
from pathlib import Path

import pytest

from agentkit.config import ConfigError, read_config
from agentkit.playbooks import (check_constants, check_playbooks, index_table, load_constants, load_playbooks,
                                read_where, split_front_matter, with_index)
from agentkit.registry import load_pack

# Write your tests below.
