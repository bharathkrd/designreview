"""
Golden values: exact answers a person wrote down once from the seed data, checked on every run.

The pack's verifiers compare the agent with the platform's data as read during the run. A golden is fixed: it
also catches a verifier that misreads the platform the same way the agent does, and a platform instance whose
data is not the seed data the tasks were written against (verifiers pass, goldens fail).

A task file lists them as [[golden]] blocks. Each has one target and one comparison:

    [[golden]]
    path = "finding.revision_delta.to_version"   # finding.* / route.* / tools / answer
    equals = 3
    note = "the newest record's note names it (seed data)"   # where a person checked the value

  targets     path      a dotted path; [n] indexes a list, [key=value] picks the first item whose key has
                        that value (so a golden does not depend on list order). Roots: "finding" (taskrun.finding), "route"
                        (taskrun.route), "tools" (the tools the journal shows, in order), "answer" (the text)
  comparisons equals    the value equals this (numbers within 1e-9; true / false strictly)
              values    the list holds exactly these items, in any order; with `field`, the items' field
              contains  a text contains this text; a list contains this item (or these items)
              only      every item of the list is one of these (repeats allowed; with `field`, the items' field)
              length    the list or text has this length
              answer_contains   the answer contains each of these texts (case ignored; no path)

The built-in check "golden" reports one outcome for each block (name = `name` or the path), "skip" when the task
has none. The built-in mutant "golden_broken" changes the first golden's value, so calibration proves the
check can fail.

Never copy a golden from the agent's output without checking it against the platform: a golden that only
repeats the agent proves nothing. scripts/make_goldens.py prints candidates for a person to check.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, model_validator

ROOTS = ("finding", "route", "tools", "answer")
_PART = re.compile(r"\.?([A-Za-z_]\w*)|\[(\d+)\]|\[([A-Za-z_]\w*)=([^\]]+)\]")
_MISSING = object()
COMPARISONS = ("equals", "values", "contains", "only", "length", "answer_contains")


class GoldenSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Optional[str] = None
    equals: Any = None
    values: Optional[List[Any]] = None
    field: Optional[str] = None
    contains: Any = None
    only: Optional[List[Any]] = None
    length: Optional[int] = None
    answer_contains: Optional[List[str]] = None
    name: Optional[str] = None
    note: str = ""

    @model_validator(mode="after")
    def _one_comparison(self) -> "GoldenSpec":
        given = [c for c in COMPARISONS if c in self.model_fields_set]
        if len(given) != 1:
            raise ValueError(f"a golden needs exactly one of {', '.join(COMPARISONS)} (got {given or 'none'})")
        if given[0] == "answer_contains":
            if self.path is not None:
                raise ValueError("answer_contains takes no path")
        else:
            if not self.path:
                raise ValueError(f"{given[0]} needs a path")
            root = _PART.match(self.path)
            if not root or root.group(1) not in ROOTS:
                raise ValueError(f"path {self.path!r} must start with one of {', '.join(ROOTS)}")
        if self.note.strip().upper().startswith("CHECK:"):
            raise ValueError("this golden was never checked (its note still says CHECK:): confirm the value "
                             "against the platform and write where in the note, or delete the block")
        if self.field is not None and given[0] not in ("values", "contains", "only"):
            raise ValueError("field goes with values, contains or only")
        return self

    @property
    def comparison(self) -> str:
        return next(c for c in COMPARISONS if c in self.model_fields_set)

    @property
    def label(self) -> str:
        return self.name or (self.path if self.path else "answer_contains")


def view(taskrun: Dict[str, Any], tools: List[str]) -> Dict[str, Any]:
    return {"finding": taskrun.get("finding") or {}, "route": taskrun.get("route") or {},
            "tools": list(tools), "answer": taskrun.get("claimed_answer") or ""}


def _step(node: Any, m: "re.Match[str]") -> Any:
    key, index, sel_key, sel_value = m.groups()
    if key is not None:
        return node[key] if isinstance(node, dict) and key in node else _MISSING
    if not isinstance(node, list):
        return _MISSING
    if index is not None:
        return node[int(index)] if int(index) < len(node) else _MISSING
    return next((x for x in node if isinstance(x, dict) and str(x.get(sel_key)) == sel_value), _MISSING)


def resolve(data: Any, path: str) -> Any:
    node, pos = data, 0
    for m in _PART.finditer(path):
        if m.start() != pos:
            return _MISSING
        pos = m.end()
        node = _step(node, m)
        if node is _MISSING:
            return _MISSING
    return node if pos == len(path) else _MISSING


def assign(data: Any, path: str, value: Any) -> bool:
    """Set the value at `path` (used by the mutant). False if the path does not exist."""
    parts = list(_PART.finditer(path))
    parent = resolve(data, path[: parts[-1].start()]) if len(parts) > 1 else data
    last = parts[-1]
    key, index, sel_key, sel_value = last.groups()
    if key is not None and isinstance(parent, dict) and key in parent:
        parent[key] = value
        return True
    if isinstance(parent, list):
        if index is not None and int(index) < len(parent):
            parent[int(index)] = value
            return True
        if sel_key is not None:
            for i, x in enumerate(parent):
                if isinstance(x, dict) and str(x.get(sel_key)) == sel_value:
                    parent[i] = value
                    return True
    return False


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9
    return a == b


def _show(v: Any) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else repr(v)
    return s if len(s) <= 160 else s[:157] + "..."


def compare(spec: GoldenSpec, data: Dict[str, Any]) -> Optional[str]:
    """None when the golden holds; otherwise why not (expected vs observed)."""
    kind = spec.comparison
    if kind == "answer_contains":
        text = (data.get("answer") or "").lower()
        missing = [p for p in spec.answer_contains or [] if p.lower() not in text]
        return f"the answer does not contain {missing}" if missing else None
    observed = resolve(data, spec.path)
    if observed is _MISSING:
        return f"no value at {spec.path}"
    if kind == "equals":
        return None if _same(observed, spec.equals) else f"expected {_show(spec.equals)}, observed {_show(observed)}"
    if kind == "length":
        n = len(observed) if isinstance(observed, (list, str, dict)) else None
        return None if n == spec.length else f"expected length {spec.length}, observed {n} ({_show(observed)})"
    items = observed
    if spec.field is not None and isinstance(observed, list):
        items = [x.get(spec.field) if isinstance(x, dict) else _MISSING for x in observed]
    if kind == "values":
        if not isinstance(items, list):
            return f"expected a list, observed {_show(observed)}"
        want = sorted(json.dumps(v, sort_keys=True, default=str) for v in spec.values or [])
        got = sorted(json.dumps(v, sort_keys=True, default=str) for v in items if v is not _MISSING)
        if want == got:
            return None
        missing = [json.loads(v) for v in want if v not in got]
        extra = [json.loads(v) for v in got if v not in want]
        return f"expected exactly {_show(spec.values)}; missing {_show(missing)}, extra {_show(extra)}"
    if kind == "only":
        if not isinstance(items, list):
            return f"expected a list, observed {_show(observed)}"
        other = [x for x in items if not any(_same(x, w) for w in spec.only or [])]
        return f"{spec.path} has items outside {_show(spec.only)}: {_show(other)}" if other else None
    # contains
    wanted = spec.contains if isinstance(spec.contains, list) else [spec.contains]
    if isinstance(items, str):
        missing = [w for w in wanted if str(w) not in items]
    elif isinstance(items, list):
        missing = [w for w in wanted if not any(_same(w, x) for x in items)]
    else:
        return f"expected text or a list at {spec.path}, observed {_show(observed)}"
    return f"{spec.path} does not contain {_show(missing)} (observed {_show(observed)})" if missing else None


def goldens_of(task: Dict[str, Any]) -> List[GoldenSpec]:
    """The task's goldens. task.json stores every field (unused ones as null); TOML has no null, so a null
    field was never written by a person and is dropped before validation."""
    return [g if isinstance(g, GoldenSpec) else GoldenSpec(**{k: v for k, v in g.items() if v is not None})
            for g in task.get("golden") or []]
