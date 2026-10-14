"""
Plans as data: a TOML file names the initial nodes and the planner rules,
validated by pydantic models (unknown keys, a bad `requires`, or a rule
with no condition are errors at load time).

    name = "my_plan"
    params = ["file_id"]                    # required run parameters

    [[nodes]]
    id = "design_file"
    action = "load_design_file"
    args = { file_id = "{file_id}" }
    after = []                              # optional
    requires = "resolved"                   # optional: resolved | settled

    mode = "eager"                          # optional: eager | superstep (engine.py)
    [channels]                              # optional shared state (channels.py)
    warnings = "topic"
    gate = "last_value"
    evidence = { kind = "barrier", names = ["revisions", "feedback"] }

    [[rules]]                               # see rule_planner.py
    name = "follow_up_when_blocked"
    [rules.when]
    node = "release_gate"
    nonempty = ["result.blockers"]
    [[rules.add]]
    id = "failed_checklists"
    action = "list_failed_checklists"
    args = { file_id = "{file_id}" }
    after = ["release_gate"]

Argument templating: a string that is exactly "{name}" is replaced by the
raw parameter value (type preserved); other strings are str.format'ed.
Unknown placeholders are an error, not a silent empty string.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agentkit.config import ConfigError, read_config, validation_message
from agentkit.graph.channels import make_channel
from agentkit.graph.engine import TaskSpec

_WHOLE = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def fill(value: Any, params: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        m = _WHOLE.match(value)
        if m:
            if m.group(1) not in params:
                raise KeyError(f"plan placeholder {{{m.group(1)}}} has no parameter")
            return params[m.group(1)]
        try:
            return value.format_map(params)
        except KeyError as e:
            raise KeyError(f"plan placeholder {e} has no parameter") from None
    if isinstance(value, dict):
        return {k: fill(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, params) for v in value]
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeModel(_Strict):
    id: str
    action: str
    args: Dict[str, Any] = Field(default_factory=dict)
    after: List[str] = Field(default_factory=list)
    requires: Literal["resolved", "settled"] = "resolved"


class EqualsModel(_Strict):
    path: str
    value: Any


class WhenModel(_Strict):
    node: str
    # The verdict the node must end with. A rule on "failed" (or "declined") is a fallback: the
    # verdict alone can be its condition, since a node that did not resolve has no data to test.
    verdict: Literal["resolved", "declined", "failed", "handed_off"] = "resolved"
    nonempty: Optional[Union[str, List[str]]] = None
    equals: Optional[EqualsModel] = None
    truthy: Optional[str] = None
    falsy: Optional[str] = None

    @model_validator(mode="after")
    def _has_a_condition(self) -> "WhenModel":
        if self.verdict == "resolved" and not any(v is not None for v in
                                                  (self.nonempty, self.equals, self.truthy, self.falsy)):
            raise ValueError("a rule on a resolved node needs at least one condition: "
                             "nonempty, equals, truthy or falsy")
        return self


class RuleModel(_Strict):
    name: Optional[str] = None
    when: WhenModel
    add: List[NodeModel] = Field(default_factory=list)
    link: List[List[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _does_something(self) -> "RuleModel":
        if not self.add and not self.link:
            raise ValueError("a rule must add nodes or link nodes")
        if any(len(pair) != 2 for pair in self.link):
            raise ValueError("each link must be [dependency, node]")
        return self


class PlanModel(_Strict):
    name: str
    params: List[str] = Field(default_factory=list)
    mode: Literal["eager", "superstep"] = "eager"
    channels: Dict[str, Union[str, Dict[str, Any]]] = Field(default_factory=dict)
    nodes: List[NodeModel] = Field(min_length=1)
    rules: List[RuleModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _channels_build(self) -> "PlanModel":
        for name, spec in self.channels.items():
            try:
                make_channel(spec)
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"channel {name!r}: {e}") from None
        return self


def node_from_dict(d: Dict[str, Any], params: Dict[str, Any], added_by: str = "plan") -> TaskSpec:
    node = d if isinstance(d, NodeModel) else NodeModel.model_validate(d)
    return TaskSpec(id=node.id, action=node.action, args=fill(node.args, params), after=list(node.after),
                    requires=node.requires, added_by=added_by)


class Plan:
    """A validated plan. `nodes` / `rules` are plain dicts (what RulePlanner reads)."""

    def __init__(self, model: PlanModel, source: str = ""):
        self.model = model
        self.name = model.name
        self.params = list(model.params)
        self.nodes = [n.model_dump() for n in model.nodes]
        self.rules = [r.model_dump(exclude_none=True) for r in model.rules]
        self.mode = model.mode
        self.channels = dict(model.channels)
        self.source = source

    def initial_tasks(self, params: Dict[str, Any]) -> List[TaskSpec]:
        missing = [p for p in self.params if p not in params]
        if missing:
            raise KeyError(f"plan {self.name!r} needs parameters {missing}")
        return [node_from_dict(n, params) for n in self.model.nodes]


def load_plan(source: Union[str, Path, Dict[str, Any]]) -> Plan:
    label = "<dict>" if isinstance(source, dict) else str(source)
    data = source if isinstance(source, dict) else read_config(Path(source))
    if isinstance(data, dict) and "name" not in data and not isinstance(source, dict):
        data = {**data, "name": Path(str(source)).stem}
    try:
        return Plan(PlanModel.model_validate(data), source=label)
    except ValidationError as e:
        raise ConfigError(validation_message(e, label)) from None
