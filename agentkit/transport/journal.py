"""
JournaledSeatClient: every MCP tool call a run made, as the transport saw it.

Wraps a SeatRpcClient and appends one JSON line per `invoke_tool` to
runs/<run_id>/tool_journal.jsonl -- tool, arguments, outcome (ok / error
kind), a small result summary, timing. This is the verifiers' source for
"which tools did the run actually touch" (e.g. "a dry run made no write
call"), so that claim never rests on the agent's report of itself.

Each call is also a "tool" span in the run's telemetry (agentkit.telemetry),
so the run tree and the journal always agree on how many calls were made.

Only tool arguments are logged -- never the bearer token, login body or
headers. Long argument strings are truncated.

Arguments are checked against the tool's input schema from the client's
catalogue before sending (required keys present, no unknown keys when the
schema forbids them, simple JSON types right). A bad call is journaled as
error_kind "bad_args" with "sent": false and raised as SeatCallFailure; it
never reaches the platform. A client without a catalogue is not checked.
"""

from __future__ import annotations

import itertools
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from agentkit.record.durable_io import JsonlAppender, read_jsonl
from agentkit.telemetry import span
from agentkit.transport.catalog import ToolCatalog
from agentkit.transport.seat_rpc import BAD_ARGS, SeatCallFailure, is_read_tool

JOURNAL_FILE = "tool_journal.jsonl"
_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": (list, tuple),
               "object": dict}
MAX_ARG_CHARS = 500
MAX_IDS = 50


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_ARG_CHARS:
        return value[:MAX_ARG_CHARS] + f"...(+{len(value) - MAX_ARG_CHARS} chars)"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value]
    return value


def summarise_result(payload: Any) -> Any:
    """Keep journals small: list pages become {total, count, ids}; single
    records become {id}; anything else becomes its type name."""
    if isinstance(payload, dict):
        rows = payload.get("data")
        if isinstance(rows, list):
            return {"total": payload.get("total"), "count": len(rows),
                    "ids": [r.get("id") for r in rows[:MAX_IDS] if isinstance(r, dict)]}
        if "id" in payload:
            return {"id": payload.get("id")}
        return {"keys": sorted(payload)[:20]}
    if isinstance(payload, list):
        return {"count": len(payload)}
    return {"type": type(payload).__name__}


def argument_problems(schema: Dict[str, Any], args: Dict[str, Any]) -> list:
    """What is wrong with `args` for a tool with this JSON input schema (empty = fine)."""
    if not schema:
        return []
    props = schema.get("properties") or {}
    problems = [f"missing required argument {k!r}" for k in schema.get("required") or [] if k not in args]
    if schema.get("additionalProperties") is False:
        problems += [f"unknown argument {k!r}" for k in args if k not in props]
    for k, v in args.items():
        kind = (props.get(k) or {}).get("type")
        types = _JSON_TYPES.get(kind) if isinstance(kind, str) else None
        if v is not None and types and not (isinstance(v, types) and not (kind in ("integer", "number")
                                                                           and isinstance(v, bool))):
            problems.append(f"argument {k!r} should be {kind}, got {type(v).__name__}")
    return problems


class JournaledSeatClient:
    def __init__(self, client: Any, path: Path, extra_read_only: tuple = (), start_seq: int = 1):
        self._client = client
        self.path = Path(path)
        self._log = JsonlAppender(self.path)
        self._seq = itertools.count(start_seq)  # a replay continues after the calls it copied
        self._seq_lock = threading.Lock()
        self.extra_read_only = frozenset(extra_read_only) | frozenset(getattr(client, "extra_read_only", ()))
        self._catalog: Any = None  # fetched on first call; False = no catalogue, so no argument checks

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    @property
    def count(self) -> int:
        return len(read_jsonl(self.path))

    def _schema(self, name: str) -> Dict[str, Any]:
        """The tool's input schema from the client's catalogue (fetched once); {} when unknown."""
        if self._catalog is None:
            fetch = getattr(self._client, "catalog", None)
            try:
                got = fetch() if callable(fetch) else False
                self._catalog = got if hasattr(got, "schema") else (ToolCatalog.from_tools(got) if got else False)
            except Exception:  # no catalogue -> no checking, never a failed run
                self._catalog = False
        return self._catalog.schema(name) if self._catalog else {}

    def invoke_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        with self._seq_lock:
            seq = next(self._seq)
        entry = {"seq": seq, "tool": name, "args": _clip(arguments or {}),
                 "read": is_read_tool(name, self.extra_read_only), "started_at": time.time()}
        problems = argument_problems(self._schema(name), arguments or {})
        if problems:
            # Refused here, not sent: a malformed call never reaches the platform.
            message = f"{name}: refused before sending -- {'; '.join(problems)}"
            self._log.append({**entry, "ok": False, "error_kind": BAD_ARGS, "error": message, "sent": False,
                              "seconds": 0.0})
            raise SeatCallFailure(message, BAD_ARGS, tool=name)
        t0 = time.time()
        with span("tool", name, seq=seq, read=entry["read"]) as s:
            try:
                result = self._client.invoke_tool(name, arguments)
            except SeatCallFailure as e:
                self._log.append({**entry, "ok": False, "error_kind": e.kind, "error": str(e)[:300],
                                  "seconds": round(time.time() - t0, 3)})
                s.set(ok=False, error_kind=e.kind, http_status=e.http_status)
                raise
            except Exception as e:
                self._log.append({**entry, "ok": False, "error_kind": "internal",
                                  "error": f"{type(e).__name__}: {e}"[:300], "seconds": round(time.time() - t0, 3)})
                s.set(ok=False, error_kind="internal")
                raise
            summary = summarise_result(result)
            self._log.append({**entry, "ok": True, "error_kind": None, "result": summary,
                              "seconds": round(time.time() - t0, 3)})
            s.set(ok=True, rows=summary.get("count") if isinstance(summary, dict) else None)
            return result


def read_journal(run_dir_or_file: Path) -> list:
    p = Path(run_dir_or_file)
    return read_jsonl(p / JOURNAL_FILE if p.is_dir() else p)
