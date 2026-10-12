"""
Checkpoint history: every meaningful state of a graph run, kept in order, so a run can
be inspected step by step ("time travel") and continued from any earlier state with a
change ("fork").

`graph.json` (agentkit-graph-v1) stays what it was: the LATEST state, rewritten after
every change. History is optional and separate: give the executor a CheckpointSaver and
it also appends a Checkpoint

    {id, ts, parent_id, metadata: {source, step, nodes, ...}, graph: <graph.json content>}

  - after the initial plan is applied       source = "input"
  - after each outcome (eager mode) or each whole step (superstep mode)   source = "loop"
  - when a run is forked from a checkpoint  source = "fork"   (parent_id = that checkpoint)

Ids are time-ordered strings (sorting them sorts by creation time), unique within the
process even when two checkpoints are made in the same nanosecond (a lock guards the
counter). `list(before=, limit=, filter=)` returns newest first.

Savers:
  MemorySaver          in-process (tests, notebooks)
  JsonlSaver(path)     append-only runs/<run_id>/checkpoints.jsonl; a torn last line from a
                       crash is skipped on read, earlier lines are never rewritten

The checkpoint record shape, the source vocabulary, the time-ordered ids and the
list(before, limit, filter) query are adapted from an external open-source agent-graph
design (referred to from outside sources); the JSONL saver is ours.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Protocol

SOURCES = ("input", "loop", "fork")
_ID_LOCK = threading.Lock()
_LAST_NS = 0


def new_checkpoint_id() -> str:
    """A UUID-shaped id whose text sorts in creation order: the high 64 bits are
    nanoseconds since the epoch (bumped by one if the clock didn't move), the low
    64 bits random."""
    global _LAST_NS
    with _ID_LOCK:
        ns = max(time.time_ns(), _LAST_NS + 1)
        _LAST_NS = ns
    return str(uuid.UUID(int=(ns << 64) | int.from_bytes(os.urandom(8), "big")))


@dataclass
class Checkpoint:
    id: str
    graph: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[str] = None
    ts: str = ""

    @property
    def source(self) -> str:
        return self.metadata.get("source", "")

    @property
    def step(self) -> int:
        return int(self.metadata.get("step") or 0)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Checkpoint":
        return cls(id=d["id"], graph=d["graph"], metadata=d.get("metadata") or {},
                   parent_id=d.get("parent_id"), ts=d.get("ts") or "")


def make_checkpoint(graph: Dict[str, Any], source: str, step: int, parent_id: Optional[str] = None,
                    **extra: Any) -> Checkpoint:
    if source not in SOURCES:
        raise ValueError(f"checkpoint source must be one of {SOURCES}")
    reserved = {"source", "step", "nodes"} & set(extra)
    if reserved:
        raise ValueError(f"checkpoint metadata keys {sorted(reserved)} are set by make_checkpoint")
    nodes = {n["id"]: (n.get("result") or {}).get("verdict") or ("paused" if n.get("interrupt") is not None
                                                                    else "pending")
             for n in graph.get("nodes") or []}
    return Checkpoint(id=new_checkpoint_id(), graph=graph, parent_id=parent_id,
                      ts=dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds"),
                      metadata={"source": source, "step": step, "nodes": nodes, **extra})


class CheckpointSaver(Protocol):
    def put(self, checkpoint: Checkpoint) -> None: ...

    def get(self, checkpoint_id: Optional[str] = None) -> Optional[Checkpoint]: ...

    def list(self, *, before: Optional[str] = None, limit: Optional[int] = None,
             filter: Optional[Dict[str, Any]] = None) -> List[Checkpoint]: ...


def _matches(cp: Checkpoint, before: Optional[str], flt: Optional[Dict[str, Any]]) -> bool:
    if before is not None and not cp.id < before:
        return False
    return all(cp.metadata.get(k) == v for k, v in (flt or {}).items())


class MemorySaver:
    def __init__(self) -> None:
        self._items: Dict[str, Checkpoint] = {}
        self._lock = threading.Lock()

    def put(self, checkpoint: Checkpoint) -> None:
        with self._lock:
            self._items[checkpoint.id] = checkpoint

    def _all(self) -> List[Checkpoint]:
        with self._lock:
            return list(self._items.values())

    def get(self, checkpoint_id: Optional[str] = None) -> Optional[Checkpoint]:
        if checkpoint_id is not None:
            with self._lock:
                return self._items.get(checkpoint_id)
        items = self._all()
        return max(items, key=lambda c: c.id) if items else None

    def list(self, *, before: Optional[str] = None, limit: Optional[int] = None,
             filter: Optional[Dict[str, Any]] = None) -> List[Checkpoint]:
        out = sorted((c for c in self._all() if _matches(c, before, filter)), key=lambda c: c.id, reverse=True)
        return out[:limit] if limit is not None else out


class JsonlSaver(MemorySaver):
    """Append-only file; the in-memory index is rebuilt from the file on open."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)
        for cp in self._read():
            self._items[cp.id] = cp

    def _read(self) -> Iterator[Checkpoint]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield Checkpoint.from_dict(json.loads(line))
                except (ValueError, KeyError):
                    continue  # a line torn by a crash mid-write

    def put(self, checkpoint: Checkpoint) -> None:
        line = json.dumps(checkpoint.to_dict(), default=str, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
            self._items[checkpoint.id] = checkpoint
