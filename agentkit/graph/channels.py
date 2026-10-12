"""
Channels: typed, shared state that graph nodes write to, with explicit merge rules.

A node's result can carry `writes = {channel: value}` (NodeResult.writes). The engine
groups the writes made in one step and hands each channel ALL of its values at once,
in node-id order, through `update(values)`. Each channel type decides how values merge:

    LastValue()          one value; two writers in the same step is an error (ChannelConflict)
    Topic(accumulate)    a list; each value (or list of values) is appended. accumulate=False
                         keeps only the latest step's values
    Reducer(op, init)    folds every value into the current one with op(current, value);
                         an Overwrite(value) replaces it instead (at most one per step)
    Ephemeral()          like LastValue but cleared again at the next step that doesn't write it
    Barrier(names)       a join: writers send their own name; it has a value (the set of
                         names) only once every expected name has arrived, and `consume()`
                         re-arms it

Why: with nodes running in parallel threads, "whoever finished last wins" is a race.
Channels make each merge rule a declared contract, and in superstep mode the order of
writes is fixed (node id), so two runs give the same state whatever the thread timing.

Every channel round-trips through `checkpoint()` / `restore()` as plain JSON, so channel
state is saved with the graph.

The channel catalogue and the update/consume/finish protocol are adapted from an external
open-source agent-graph design (referred to from outside sources); names, the
JSON checkpoint form and the error types are ours.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


class NoValue(LookupError):
    """get() on a channel that has nothing yet (or a barrier still waiting)."""


class ChannelConflict(ValueError):
    """Writes in one step that the channel can't merge (e.g. two LastValue writers)."""


_EMPTY = object()


class Overwrite:
    """Wrap a value written to a Reducer to replace its state instead of folding into it."""

    __slots__ = ("value",)

    def __init__(self, value: Any):
        self.value = value

    def __repr__(self) -> str:
        return f"Overwrite({self.value!r})"


class Channel:
    kind = "channel"

    def update(self, values: Sequence[Any]) -> bool:
        """Apply one step's writes; return True if the visible value changed."""
        raise NotImplementedError

    def get(self) -> Any:
        raise NotImplementedError

    def available(self) -> bool:
        try:
            self.get()
            return True
        except NoValue:
            return False

    def consume(self) -> bool:
        """Called after the value was read by the node(s) it triggered."""
        return False

    def finish(self) -> bool:
        """Called once when the run has nothing left to do."""
        return False

    def checkpoint(self) -> Any:
        raise NotImplementedError

    def restore(self, saved: Any) -> None:
        raise NotImplementedError

    def spec(self) -> Dict[str, Any]:
        """How to rebuild an empty copy of this channel (saved with checkpoints)."""
        return {"kind": self.kind}


class LastValue(Channel):
    kind = "last_value"

    def __init__(self) -> None:
        self.value: Any = _EMPTY

    def update(self, values: Sequence[Any]) -> bool:
        if not values:
            return False
        if len(values) > 1:
            raise ChannelConflict(f"{len(values)} writes in one step to a single-value channel")
        self.value = values[-1]
        return True

    def get(self) -> Any:
        if self.value is _EMPTY:
            raise NoValue("no value yet")
        return self.value

    def checkpoint(self) -> Any:
        return None if self.value is _EMPTY else {"value": self.value}

    def restore(self, saved: Any) -> None:
        self.value = _EMPTY if saved is None else saved["value"]


class Ephemeral(LastValue):
    kind = "ephemeral"

    def update(self, values: Sequence[Any]) -> bool:
        if not values:
            had = self.value is not _EMPTY
            self.value = _EMPTY
            return had
        return super().update(values)


class Topic(Channel):
    kind = "topic"

    def __init__(self, accumulate: bool = True) -> None:
        self.accumulate = accumulate
        self.values: List[Any] = []

    def update(self, values: Sequence[Any]) -> bool:
        changed = False
        if not self.accumulate:
            changed = bool(self.values)
            self.values = []
        for v in values:
            if isinstance(v, list):
                self.values.extend(v)
                changed = changed or bool(v)
            else:
                self.values.append(v)
                changed = True
        return changed

    def get(self) -> List[Any]:
        if not self.values:
            raise NoValue("empty topic")
        return list(self.values)

    def checkpoint(self) -> Any:
        return list(self.values)

    def restore(self, saved: Any) -> None:
        self.values = list(saved or [])

    def spec(self) -> Dict[str, Any]:
        return {"kind": self.kind, "accumulate": self.accumulate}


REDUCERS: Dict[str, Tuple[Callable[[Any, Any], Any], Callable[[], Any]]] = {
    "sum": (lambda a, b: a + b, int),
    "max": (max, lambda: _EMPTY),
    "min": (min, lambda: _EMPTY),
    "extend": (lambda a, b: [*a, *(b if isinstance(b, list) else [b])], list),
    "merge": (lambda a, b: {**a, **b}, dict),
    "union": (lambda a, b: sorted(set(a) | set(b if isinstance(b, (list, set, tuple)) else [b]), key=str), list),
}


class Reducer(Channel):
    """Folds values with a binary operator. `op` is a callable or one of the
    named reducers above (a named one can be saved and rebuilt from a plan file)."""

    kind = "reducer"

    def __init__(self, op: Any, initial: Optional[Callable[[], Any]] = None) -> None:
        self.op_name = op if isinstance(op, str) else None
        if isinstance(op, str):
            if op not in REDUCERS:
                raise ValueError(f"unknown reducer {op!r}; one of {sorted(REDUCERS)}")
            op, default_initial = REDUCERS[op]
            initial = initial or default_initial
        self.op = op
        self.initial = initial
        self.value: Any = initial() if initial else _EMPTY

    def update(self, values: Sequence[Any]) -> bool:
        if not values:
            return False
        overwrites = [v for v in values if isinstance(v, Overwrite)]
        if len(overwrites) > 1:
            raise ChannelConflict("more than one Overwrite in one step")
        changed = False
        for v in values:
            if isinstance(v, Overwrite):
                self.value = v.value
            elif self.value is _EMPTY:
                self.value = v
            else:
                self.value = self.op(self.value, v)
            changed = True
        return changed

    def get(self) -> Any:
        if self.value is _EMPTY:
            raise NoValue("no value yet")
        return self.value

    def checkpoint(self) -> Any:
        return None if self.value is _EMPTY else {"value": self.value}

    def restore(self, saved: Any) -> None:
        self.value = (self.initial() if self.initial else _EMPTY) if saved is None else saved["value"]

    def spec(self) -> Dict[str, Any]:
        if self.op_name is None:
            raise ValueError("a Reducer with a custom callable can't be rebuilt from a checkpoint; "
                             "use a named reducer or pass the channels when loading")
        return {"kind": self.kind, "op": self.op_name}


class Barrier(Channel):
    """Waits for every named writer. Writers send their own name."""

    kind = "barrier"

    def __init__(self, names: Iterable[str]) -> None:
        self.names = frozenset(names)
        if not self.names:
            raise ValueError("a barrier needs at least one name")
        self.seen: set = set()

    def update(self, values: Sequence[Any]) -> bool:
        changed = False
        for v in values:
            if v not in self.names:
                raise ChannelConflict(f"{v!r} is not one of the barrier's names {sorted(self.names)}")
            if v not in self.seen:
                self.seen.add(v)
                changed = True
        return changed

    def get(self) -> List[str]:
        if self.seen != self.names:
            raise NoValue(f"still waiting for {sorted(self.names - self.seen)}")
        return sorted(self.seen)

    def consume(self) -> bool:
        if self.seen == self.names:
            self.seen = set()
            return True
        return False

    def checkpoint(self) -> Any:
        return sorted(self.seen)

    def restore(self, saved: Any) -> None:
        self.seen = set(saved or [])

    def spec(self) -> Dict[str, Any]:
        return {"kind": self.kind, "names": sorted(self.names)}


def make_channel(spec: Any) -> Channel:
    """Build a channel from its plan/checkpoint form:
    "last_value" | "ephemeral" | "topic" | {"kind": "topic", "accumulate": false} |
    {"kind": "reducer", "op": "sum"} | {"kind": "barrier", "names": [...]}."""
    if isinstance(spec, Channel):
        return spec
    if isinstance(spec, str):
        spec = {"kind": spec}
    kind = spec.get("kind")
    if kind == "last_value":
        return LastValue()
    if kind == "ephemeral":
        return Ephemeral()
    if kind == "topic":
        return Topic(accumulate=spec.get("accumulate", True))
    if kind == "reducer":
        return Reducer(spec["op"])
    if kind == "barrier":
        return Barrier(spec["names"])
    raise ValueError(f"unknown channel kind {kind!r}")


class ChannelState:
    """All of a run's channels, their versions, and the step counter.

    `apply(writes_by_node)` is one step: writes are grouped per channel in
    node-id order, each written channel gets every value at once, channels
    nobody wrote get an empty update (an Ephemeral clears itself), and every
    channel that changed gets the same new version number."""

    def __init__(self, channels: Optional[Dict[str, Any]] = None) -> None:
        self.channels: Dict[str, Channel] = {name: make_channel(c) for name, c in (channels or {}).items()}
        self.versions: Dict[str, int] = {name: 0 for name in self.channels}
        self.step = 0

    def __bool__(self) -> bool:
        return bool(self.channels)

    def apply(self, writes_by_node: Dict[str, Dict[str, Any]]) -> List[str]:
        grouped: Dict[str, List[Any]] = {}
        for node_id in sorted(writes_by_node):
            for name, value in (writes_by_node[node_id] or {}).items():
                if name not in self.channels:
                    raise ChannelConflict(f"node {node_id} wrote to unknown channel {name!r}")
                grouped.setdefault(name, []).append(value)
        self.step += 1
        changed = []
        for name in sorted(self.channels):
            try:
                if self.channels[name].update(grouped.get(name, [])):
                    self.versions[name] = self.step
                    changed.append(name)
            except ChannelConflict as e:
                raise ChannelConflict(f"channel {name!r}: {e}") from None
        return changed

    def values(self) -> Dict[str, Any]:
        out = {}
        for name, ch in self.channels.items():
            try:
                out[name] = ch.get()
            except NoValue:
                continue
        return out

    def consume(self, names: Iterable[str]) -> None:
        for name in names:
            if name in self.channels and self.channels[name].consume():
                self.versions[name] = self.step

    def finish(self) -> None:
        for name, ch in self.channels.items():
            if ch.finish():
                self.versions[name] = self.step

    def to_dict(self) -> Dict[str, Any]:
        return {"step": self.step, "specs": {n: c.spec() for n, c in self.channels.items()},
                "values": {n: c.checkpoint() for n, c in self.channels.items()},
                "versions": dict(self.versions)}

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]], channels: Optional[Dict[str, Any]] = None) -> "ChannelState":
        d = d or {}
        state = cls(channels if channels is not None else d.get("specs") or {})
        for name, saved in (d.get("values") or {}).items():
            if name in state.channels:
                state.channels[name].restore(saved)
        state.versions.update({k: v for k, v in (d.get("versions") or {}).items() if k in state.channels})
        state.step = int(d.get("step") or 0)
        return state
