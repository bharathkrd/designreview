"""
Spans: one timed, attributed record per unit of work, nested into a run tree.

    tracer = Tracer(run_id)
    with use_tracer(tracer):
        with span("task", task_id, tenant=...) as root:
            with span("node", node_id, action=...) as node:
                with span("tool", "Record.get") as call:
                    call.set(ok=True, rows=3)

What callers can rely on:
- `span(kind, name, **attrs)` with no active tracer is a no-op (yields a
  span-shaped object whose `set` does nothing), so instrumented code behaves
  exactly as before when nobody is tracing.
- A span's parent is whatever span is current in the calling context
  (contextvars). Thread pools don't copy context, so submit work as
  `pool.submit(bind_context(fn), ...)`: the worker then sees the submitter's
  current span as its parent.
- An exception leaving a span marks it status="error" with "Type: message" and
  is re-raised unchanged.
- `annotate(**attrs)` / `add_event(name, **attrs)` act on the current span, if
  any -- for code (the wire, the session) that shouldn't know about spans.
- `Tracer(handlers=[...])`: each handler may define on_<run_type>_start /
  _end / _error(span) (run_type: chain | tool | llm | retriever). A handler
  that raises is ignored unless it sets `raise_error = True`.
- Kinds: task | node | tool | llm | step | retriever. Each also carries a
  coarser `run_type` (chain | tool | llm | retriever).

How it works (the algorithm):
- Every span gets a random id. A root's `trace_id` is its own id; a child
  inherits its parent's. `dotted_order` is the root-to-span path of segments
  "<start time %Y%m%dT%H%M%S%fZ><id>" joined by ".", so sorting spans by it
  sorts the whole tree, parents before children, siblings by start time. A
  child's start is never earlier than its parent's, which keeps that order valid.
- The current span lives in a ContextVar; a span opened in that context
  becomes its child. Work handed to another thread runs in a copy of the
  submitter's context (`bind_context`), so the tree survives a thread pool.
- The tracer keeps an id -> span map; a span whose parent it doesn't know
  becomes a root rather than being dropped.

Provenance: adapted from an external open-source tracing design (run trees
with dotted ordering and context-variable propagation), referred to from
outside sources and rebuilt here in plain Python with no third-party
dependency.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import functools
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, TypeVar

KINDS = ("task", "node", "tool", "llm", "step", "retriever")
RUN_TYPE = {"task": "chain", "node": "chain", "step": "chain", "tool": "tool", "llm": "llm",
            "retriever": "retriever"}
DOTTED_TIME = "%Y%m%dT%H%M%S%fZ"

_TRACER: contextvars.ContextVar[Optional["Tracer"]] = contextvars.ContextVar("agentkit_tracer", default=None)
_CURRENT: contextvars.ContextVar[Optional["Span"]] = contextvars.ContextVar("agentkit_span", default=None)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class Span:
    kind: str
    name: str
    span_id: str
    parent_id: Optional[str]
    trace_id: str
    dotted_order: str
    start_time: str  # ISO-8601 UTC wall clock (for humans and ordering)
    start_ms: float  # monotonic, relative to the tracer's start (for durations)
    attrs: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    end_ms: Optional[float] = None
    duration_ms: Optional[float] = None
    status: str = "running"  # running | ok | error
    error: Optional[str] = None

    @property
    def run_type(self) -> str:
        return RUN_TYPE[self.kind]

    def set(self, **attrs: Any) -> "Span":
        self.attrs.update(attrs)
        return self

    def add_event(self, name: str, **attrs: Any) -> None:
        self.events.append({"name": name, "time": _now_iso(), **attrs})

    def to_dict(self) -> Dict[str, Any]:
        return {"span_id": self.span_id, "parent_id": self.parent_id, "trace_id": self.trace_id,
                "dotted_order": self.dotted_order, "kind": self.kind, "run_type": self.run_type, "name": self.name,
                "start_time": self.start_time, "start_ms": self.start_ms, "end_ms": self.end_ms,
                "duration_ms": self.duration_ms, "status": self.status, "error": self.error,
                "attrs": dict(self.attrs), "events": list(self.events)}


class _NullSpan:
    """What span() yields when nobody is tracing: accepts everything, records nothing."""

    span_id = None

    def set(self, **attrs: Any) -> "_NullSpan":
        return self

    def add_event(self, name: str, **attrs: Any) -> None:
        return None


NULL_SPAN = _NullSpan()


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


class Tracer:
    """Collects the spans of one run. Thread-safe."""

    def __init__(self, run_id: str = "", clock: Callable[[], float] = time.perf_counter,
                 handlers: Optional[List[Any]] = None):
        self.run_id = run_id
        self.handlers = list(handlers or [])
        self._clock = clock
        self._t0 = clock()
        self._lock = threading.Lock()
        self.spans: List[Span] = []  # in start order
        self._by_id: Dict[str, Span] = {}

    def _elapsed_ms(self) -> float:
        return round((self._clock() - self._t0) * 1000.0, 3)

    def start(self, kind: str, name: str, parent: Optional[Span], attrs: Dict[str, Any]) -> Span:
        if kind not in KINDS:
            raise ValueError(f"unknown span kind {kind!r}; one of {KINDS}")
        span_id = uuid.uuid4().hex
        now = dt.datetime.now(dt.timezone.utc)
        with self._lock:
            known_parent = parent if parent is not None and parent.span_id in self._by_id else None
            if known_parent is not None:
                # a child never starts before its parent, so dotted_order stays sorted
                parent_start = dt.datetime.fromisoformat(known_parent.start_time)
                now = max(now, parent_start)
            segment = now.strftime(DOTTED_TIME) + span_id
            span = Span(kind=kind, name=name, span_id=span_id,
                        parent_id=known_parent.span_id if known_parent else None,
                        trace_id=known_parent.trace_id if known_parent else span_id,
                        dotted_order=(known_parent.dotted_order + "." + segment) if known_parent else segment,
                        start_time=now.isoformat(timespec="microseconds"), start_ms=self._elapsed_ms(),
                        attrs=dict(attrs))
            self.spans.append(span)
            self._by_id[span_id] = span
        self._notify(f"on_{span.run_type}_start", span)
        return span

    def _notify(self, method: str, span: Span) -> None:
        for handler in self.handlers:
            fn = getattr(handler, method, None)
            if fn is None:
                continue
            try:
                fn(span)
            except Exception:
                if getattr(handler, "raise_error", False):
                    raise

    def finish(self, span: Span, error: Optional[BaseException] = None) -> None:
        end = self._elapsed_ms()
        with self._lock:
            span.end_ms = end
            span.duration_ms = round(end - span.start_ms, 3)
            if error is not None:
                span.status, span.error = "error", f"{type(error).__name__}: {error}"[:500]
            else:
                span.status = "ok"
        self._notify(f"on_{span.run_type}_{'error' if error is not None else 'end'}", span)

    def to_dicts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [s.to_dict() for s in self.spans]


def current_tracer() -> Optional[Tracer]:
    return _TRACER.get()


def current_span() -> Optional[Span]:
    return _CURRENT.get()


@contextmanager
def use_tracer(tracer: Tracer) -> Iterator[Tracer]:
    """Make `tracer` collect every span opened in this context (and in work
    submitted through bind_context)."""
    t_token = _TRACER.set(tracer)
    s_token = _CURRENT.set(None)
    try:
        yield tracer
    finally:
        _CURRENT.reset(s_token)
        _TRACER.reset(t_token)


@contextmanager
def span(kind: str, name: str, **attrs: Any) -> Iterator[Any]:
    tracer = _TRACER.get()
    if tracer is None:
        yield NULL_SPAN
        return
    s = tracer.start(kind, name, _CURRENT.get(), attrs)
    token = _CURRENT.set(s)
    try:
        yield s
    except BaseException as e:
        tracer.finish(s, e)
        raise
    else:
        tracer.finish(s)
    finally:
        _CURRENT.reset(token)


def traced(kind: str, name: Optional[str] = None, **attrs: Any) -> Callable[[F], F]:
    """Decorator form of span(): the wrapped function's call is one span."""
    def deco(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(kind, name or fn.__name__, **attrs):
                return fn(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return deco


def bind_context(fn: F) -> F:
    """Bind `fn` to a copy of the CURRENT context (tracer + current span), for
    work handed to another thread. Call it in the submitting thread."""
    ctx = contextvars.copy_context()

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        return ctx.copy().run(fn, *args, **kwargs)
    return run  # type: ignore[return-value]


def annotate(**attrs: Any) -> None:
    """Add attributes to the current span, if one is open."""
    s = _CURRENT.get()
    if s is not None:
        s.set(**attrs)


def add_event(name: str, **attrs: Any) -> None:
    """Record an event (a retry, a re-login, a cache hit) on the current span, if any."""
    s = _CURRENT.get()
    if s is not None:
        s.add_event(name, **attrs)
