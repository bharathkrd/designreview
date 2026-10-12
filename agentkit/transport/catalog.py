"""
ToolCatalog: what a seat's tools/list says, as one comparable value.

- `fingerprint()` -- 16 hex chars of SHA-256 over the sorted tool names and
  their canonical input schemas. Recorded in every run record and in each
  platform fixture, so "the platform changed its tools since the fixture was
  captured" is one string comparison (agentkit.harness.preflight).
- `check_requirements({tool: [args we send]})` -- the tools a pack depends on
  are still there, and none now requires an argument we don't send.
- `read_only_hint(tool)` -- the server's own readOnlyHint annotation, or None
  when the catalogue doesn't say (a name-only catalogue never claims False).

Accepts full tool definitions (dicts with name / inputSchema / annotations) or
bare names (older fixtures store names only; their fingerprint covers names).

Provenance: the catalogue-fingerprint idea (hash the sorted tool names and
input schemas; check required tools and arguments) is referred from an
outside source and rebuilt here, with requirements passed in by the pack and
None for "unknown" read-only hints.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Union

ToolDef = Union[str, Mapping[str, Any]]


@dataclass(frozen=True)
class ToolCatalog:
    tools: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_tools(cls, tools: Iterable[ToolDef]) -> "ToolCatalog":
        out: Dict[str, Dict[str, Any]] = {}
        for t in tools or []:
            if isinstance(t, str):
                out[t] = {"name": t}
            elif isinstance(t, Mapping) and t.get("name"):
                out[str(t["name"])] = dict(t)
        return cls(out)

    @property
    def names(self) -> FrozenSet[str]:
        return frozenset(self.tools)

    def __contains__(self, name: str) -> bool:
        return name in self.tools

    def __len__(self) -> int:
        return len(self.tools)

    def schema(self, name: str) -> Dict[str, Any]:
        return dict((self.tools.get(name) or {}).get("inputSchema") or {})

    def required_args(self, name: str) -> List[str]:
        return list(self.schema(name).get("required") or [])

    def read_only_hint(self, name: str) -> Optional[bool]:
        annotations = (self.tools.get(name) or {}).get("annotations")
        if not isinstance(annotations, Mapping) or "readOnlyHint" not in annotations:
            return None
        return bool(annotations["readOnlyHint"])

    def fingerprint(self) -> str:
        canon = sorted((n, json.dumps(self.schema(n), sort_keys=True)) for n in self.tools)
        return hashlib.sha256(json.dumps(canon).encode("utf-8")).hexdigest()[:16]

    def check_requirements(self, requirements: Mapping[str, Iterable[str]]) -> List[str]:
        """Problems with the tools a caller depends on (empty list = all good).
        `requirements` maps each tool to the arguments the caller sends."""
        problems: List[str] = []
        for name in sorted(requirements or {}):
            if name not in self.tools:
                problems.append(f"missing tool {name}")
                continue
            extra = sorted(set(self.required_args(name)) - set(requirements[name] or ()))
            if extra:
                problems.append(f"{name} now requires {extra}")
        return problems

    def summary(self) -> Dict[str, Any]:
        return {"count": len(self.tools), "fingerprint": self.fingerprint()}
