"""
SimPlatform: replays a SeatFixture offline, for the agent AND the harness.

It presents both surfaces the code uses:
  - agent side: invoke_tool / offers / seat_catalog / initialize (like SeatRpcClient)
  - harness side: `.rest` (list_all / get / raw) and `.mcp` (itself), so it can
    stand in for GroundTruthReader.

Replay is exact: a call whose (tool, canonical args) was not captured raises
SeatCallFailure(kind="unclassified", "not in fixture ...") -- a gap in the
fixture is loud, never a silent empty result.

Faults (strings), for testing how the agent and harness behave when things go wrong:
  drop_tool:<tool>               the tool is absent from the catalogue and refuses (not_in_seat)
  fail_once:<tool>:<kind>        the next call of <tool> fails with <kind> (e.g. flaky, missing)
  fail_always:<tool>:<kind>      every call of <tool> fails with <kind>
  edit_text:<old>=><new>         after apply_edits(), every recorded result has <old> replaced
                                 by <new> -- "another team edited the record during the run"
  fail_times:<tool>:<kind>:<n>   the next <n> calls of <tool> fail with <kind> (e.g. a rate limit
                                 that clears after a few retries)
  inject_text:<tool>:<field>=<text>
                                 every <field> string in <tool>'s results gets " <text>" appended,
                                 BEFORE the agent reads it -- an indirect prompt injection planted in
                                 platform data (the attacker never talks to the agent)
  truncate:<tool>:<n>            <tool>'s "data" list is cut to its first <n> rows while "total"
                                 still says how many there are -- a partial payload
  rename_field:<tool>:<old>=<new>
                                 every <old> key in <tool>'s results is renamed <new> -- the
                                 platform changed its schema
Call and result faults fire only while `armed` is True; the harness arms them
around the agent's run so its own ground-truth reads are not disturbed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from agentkit.sim.fixture import SeatFixture, canonical
from agentkit.transport import KINDS, NOT_IN_SEAT, UNCLASSIFIED, SeatCallFailure
from agentkit.transport.catalog import ToolCatalog

FAULT_KINDS = ("drop_tool", "fail_once", "fail_always", "fail_times", "edit_text", "inject_text", "truncate",
               "rename_field")
RESULT_FAULTS = ("inject_text", "truncate", "rename_field")


def parse_fault(fault: str) -> Tuple[str, List[str]]:
    kind, _, rest = fault.partition(":")
    if kind not in FAULT_KINDS:
        raise ValueError(f"unknown fault {fault!r}; kinds: {', '.join(FAULT_KINDS)}")
    if kind == "edit_text":
        old, sep, new = rest.partition("=>")
        if not sep or not old:
            raise ValueError(f"edit_text fault needs '<old>=><new>': {fault!r}")
        return kind, [old, new]
    if kind in ("inject_text", "rename_field"):
        tool, _, spec = rest.partition(":")
        field, sep, value = spec.partition("=")
        if not tool or not field or not sep or not value:
            raise ValueError(f"{kind} fault needs '<tool>:<field>=<value>': {fault!r}")
        return kind, [tool, field, value]
    parts = rest.split(":") if rest else []
    need = {"drop_tool": 1, "fail_once": 2, "fail_always": 2, "fail_times": 3, "truncate": 2}[kind]
    if len(parts) != need or not all(parts):
        raise ValueError(f"fault {fault!r} needs {need} argument(s)")
    if kind in ("fail_once", "fail_always", "fail_times") and parts[1] not in KINDS:
        raise ValueError(f"fault {fault!r}: unknown failure kind {parts[1]!r}")
    if kind in ("fail_times", "truncate") and not parts[-1].isdigit():
        raise ValueError(f"fault {fault!r}: the count must be a whole number")
    return kind, parts


def _append_to_field(obj: Any, field: str, text: str) -> Any:
    if isinstance(obj, dict):
        return {k: (f"{v} {text}" if k == field and isinstance(v, str) else _append_to_field(v, field, text))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_append_to_field(v, field, text) for v in obj]
    return obj


def _rename_key(obj: Any, old: str, new: str) -> Any:
    if isinstance(obj, dict):
        return {(new if k == old else k): _rename_key(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename_key(v, old, new) for v in obj]
    return obj


def _replace_text(obj: Any, old: str, new: str) -> Any:
    if isinstance(obj, str):
        return obj.replace(old, new)
    if isinstance(obj, dict):
        return {k: _replace_text(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_text(v, old, new) for v in obj]
    return obj


class _SimRest:
    def __init__(self, platform: "SimPlatform"):
        self._p = platform

    def list_all(self, entity: str, **params: Any) -> Any:
        return self._p._replay("rest", f"list_all:{entity}", params)

    def get(self, entity: str, record_id: str) -> Any:
        return self._p._replay("rest", f"get:{entity}", {"id": record_id})

    def raw(self, path: str, **params: Any) -> Any:
        return self._p._replay("rest", f"raw:{path}", params)


class SimPlatform:
    def __init__(self, fixture: Union[SeatFixture, str, Path], faults: Iterable[str] = (),
                 extra_read_only: Iterable[str] = ()):
        self.fixture = fixture if isinstance(fixture, SeatFixture) else SeatFixture.load(Path(fixture))
        self._calls = self.fixture.index()
        self.faults = [parse_fault(f) for f in faults if f]
        self.fired: set = set()
        self.fired_count: Dict[int, int] = {}
        self.armed = True
        self.edits_applied = False
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []  # (channel, op, args) as seen
        self.extra_read_only = frozenset(extra_read_only)
        self.rest = _SimRest(self)
        self.mcp = self
        self.dropped = {args[0] for kind, args in self.faults if kind == "drop_tool"}

    # ---- agent / harness MCP surface -------------------------------------------------

    def initialize(self) -> Dict[str, Any]:
        return {"protocolVersion": "sim", "serverInfo": {"name": "SimPlatform", "tenant": self.fixture.tenant}}

    def seat_catalog(self, refresh: bool = False) -> Dict[str, dict]:
        defs = {d.get("name"): d for d in self.fixture.tool_defs if isinstance(d, dict)}
        return {t: defs.get(t, {"name": t}) for t in self.fixture.tools if t not in self.dropped}

    def catalog(self, refresh: bool = False) -> ToolCatalog:
        return ToolCatalog.from_tools(self.seat_catalog().values())

    def offers(self, tool: str) -> bool:
        return tool in self.seat_catalog()

    def invoke_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        if name in self.dropped:
            self.calls.append(("mcp", name, dict(arguments or {})))
            raise SeatCallFailure(f"{name}: tool not available to this seat (sim: dropped)", NOT_IN_SEAT, tool=name)
        return self._replay("mcp", name, arguments or {})

    # ---- replay ------------------------------------------------------------------------

    def _call_fault(self, op: str) -> Optional[str]:
        if not self.armed:
            return None
        for i, (kind, args) in enumerate(self.faults):
            if kind == "fail_always" and args[0] == op:
                return args[1]
            if kind == "fail_once" and args[0] == op and i not in self.fired:
                self.fired.add(i)
                return args[1]
            if kind == "fail_times" and args[0] == op and self.fired_count.get(i, 0) < int(args[2]):
                self.fired_count[i] = self.fired_count.get(i, 0) + 1
                return args[1]
        return None

    def _result_faults(self, op: str, result: Any) -> Any:
        if not self.armed:
            return result
        for kind, args in self.faults:
            if kind not in RESULT_FAULTS or args[0] != op:
                continue
            if kind == "inject_text":
                result = _append_to_field(result, args[1], args[2])
            elif kind == "rename_field":
                result = _rename_key(result, args[1], args[2])
            elif kind == "truncate" and isinstance(result, dict) and isinstance(result.get("data"), list):
                rows = result["data"]
                result = {**result, "data": rows[:int(args[1])], "total": max(len(rows), result.get("total") or 0)}
        return result

    def _replay(self, channel: str, op: str, args: Dict[str, Any]) -> Any:
        self.calls.append((channel, op, dict(args)))
        tool = op if channel == "mcp" else op.partition(":")[2]
        fault_kind = self._call_fault(op if channel == "mcp" else tool)
        if fault_kind:
            raise SeatCallFailure(f"{op}: injected fault ({fault_kind})", fault_kind, tool=op)
        rec = self._calls.get((channel, op, canonical(args)))
        if rec is None:
            raise SeatCallFailure(f"{op}({canonical(args)}): not in fixture -- re-capture it", UNCLASSIFIED, tool=op)
        if rec.error_kind:
            raise SeatCallFailure(rec.error or f"{op}: {rec.error_kind}", rec.error_kind, tool=op)
        result = json.loads(json.dumps(rec.result))  # a fresh copy every time
        return self._result_faults(op, result) if channel == "mcp" else result

    # ---- scripted drift ------------------------------------------------------------------

    def apply_edits(self) -> int:
        """Fire every edit_text fault: rewrite recorded results in place."""
        n = 0
        for kind, args in self.faults:
            if kind != "edit_text":
                continue
            old, new = args
            for key, rec in self._calls.items():
                if rec.result is not None:
                    changed = _replace_text(rec.result, old, new)
                    if changed != rec.result:
                        self._calls[key] = rec.model_copy(update={"result": changed})
                        n += 1
        self.edits_applied = True
        return n

    def tools_called(self) -> List[str]:
        return [op for ch, op, _ in self.calls if ch == "mcp"]
