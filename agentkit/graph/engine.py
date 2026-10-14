"""
Live task graph: nodes run when their dependencies allow, in parallel, and
a planner may extend the graph in reaction to what just finished.

Rules the engine enforces (none of them domain-specific):
- A node names a registered *action*, never a raw tool. A patch naming
  anything else is rejected, so no plan or planner can reach a tool the
  pack didn't expose.
- `requires="resolved"`: run only if every dependency RESOLVED, otherwise
  the node is BYPASSED with the reason. `requires="settled"`: run once
  every dependency has finished in any verdict (a partial join -- one bad
  branch can't take the other answers down with it).
- A whole patch is validated before anything changes: unknown action,
  duplicate id, missing dependency, an edge into a node that already
  started, a cycle, or exceeding the node budget -> ValueError, graph
  untouched.
- Transport errors map to verdicts: MISSING / NOT_IN_SEAT / DENIED ->
  DECLINED (the platform said no -- a refusal, not a crash); FLAKY is
  retried per the action's RetryPolicy (agentkit.graph.policies; never for
  writes) then FAILED; anything else FAILED.
- A write action in a dry run is never called. If it has a `preview`, the
  node ends HANDED_OFF with {"would_file": <preview>, "filed": False} -- what
  a person would receive, gradable without touching the platform; an empty
  preview (nothing to file) is RESOLVED. Without a preview it is DECLINED.
- After every outcome the whole graph is checkpointed (atomic write); a
  checkpoint can be loaded and continued. Nodes that were mid-flight at a
  crash go back to pending on resume.

Two scheduling modes (LiveGraphExecutor(mode=...)):
- "eager" (default): a node starts the moment its dependencies allow, and the
  planner reacts to each outcome as it arrives.
- "superstep": bulk-synchronous steps. Every ready node runs in parallel
  against the same snapshot of earlier results; the step ends when all of
  them have finished; then their outcomes are recorded, their channel writes
  applied and the planner consulted, all in node-id order. Thread timing can
  then never change the state, the planner's patches or the checkpoint
  sequence. The cost: a step waits for its slowest node. `max_steps` bounds a
  run that keeps growing (StepLimitExceeded).

Shared state between nodes: optional channels (agentkit.graph.channels). A
node writes with NodeResult(writes={...}); an action reads the current values
with read_channels(). In superstep mode a step's writes are applied together,
so two writers of a single-value channel in one step is an error, not a race.

Pausing for a person: an action may call interrupt(payload). The node stops
without a verdict ("paused"); nodes that depend on it wait; everything else
finishes. store.resume(node_id, answer) and continue_from() run it again, and
this time interrupt() returns the answer. With approve_writes=True the engine
does this itself before any real (non-dry-run) write: the payload carries the
write's preview, and only True / {"approved": true} lets the write run;
any other answer ends the node DECLINED.

History: with a CheckpointSaver (agentkit.graph.checkpoint) every step is
also kept as a checkpoint, and GraphStore.fork() continues from any state
with some node results replaced.

The scheduling modes, channels, pause/resume and fork follow an external
open-source agent-graph design (referred to from outside sources),
re-implemented here without it.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from concurrent.futures import ALL_COMPLETED, FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, Union

from agentkit.graph.channels import ChannelState
from agentkit.graph.checkpoint import Checkpoint, CheckpointSaver, make_checkpoint
from agentkit.graph.node_result import (BYPASSED, DECLINED, FAILED, HANDED_OFF, RESOLVED, NodeResult)
from agentkit.graph.policies import policy_for
from agentkit.record.durable_io import dump_record, load_record
from agentkit.registry import Registry
from agentkit.telemetry import add_event, bind_context, span
from agentkit.transport.seat_rpc import DENIED, MISSING, NOT_IN_SEAT, SeatCallFailure

logger = logging.getLogger("agentkit.graph")

CHECKPOINT_FORMAT = "agentkit-graph-v1"
DEFAULT_MAX_NODES = 30
DEFAULT_MAX_STEPS = 50
MODES = ("eager", "superstep")
REQUIRES = ("resolved", "settled")
_DECLINE_KINDS = {MISSING: "record not found", NOT_IN_SEAT: "tool not available to this seat",
                  DENIED: "access denied"}


class ActionTimeout(Exception):
    """One attempt of an action ran past its timeout_s."""


class StepLimitExceeded(RuntimeError):
    """A superstep run needed more than max_steps steps (a plan that keeps growing)."""


class NodeInterrupt(Exception):
    """Raised by interrupt(): the node pauses until a person answers."""

    def __init__(self, value: Any):
        super().__init__("node paused for input")
        self.value = value


@dataclass
class _Paused:
    value: Any


def interrupt(value: Any) -> Any:
    """Pause the current node with `value` (what to show a person). After
    store.resume(node_id, answer) the node runs again and this returns `answer`."""
    current = _CURRENT_NODE.get()
    if current is None:
        raise RuntimeError("interrupt() called outside a running graph node")
    spec, _ = current
    if spec.resume is not None:
        return spec.resume.get("value")
    raise NodeInterrupt(value)


def read_channels() -> Dict[str, Any]:
    """The current values of the run's channels, from inside an action."""
    current = _CURRENT_NODE.get()
    return current[1].channel_values() if current else {}


def approved(answer: Any) -> bool:
    return answer is True or (isinstance(answer, dict) and answer.get("approved") is True)


@dataclass
class RunEnv:
    """What an action gets besides its own args."""

    client: Any  # anything with invoke_tool(name, args) (+ offers(tool) for catalogue checks)
    run_id: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    tenant: str = ""
    gateway: Any = None
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskSpec:
    id: str
    action: str
    args: Dict[str, Any] = field(default_factory=dict)
    after: List[str] = field(default_factory=list)
    requires: str = "resolved"
    added_by: str = "plan"  # "plan" | "planner"
    result: Optional[NodeResult] = None
    attempts: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    interrupt: Any = None  # what the node paused with (interrupt())
    resume: Optional[Dict[str, Any]] = None  # {"value": the person's answer}

    @property
    def state(self) -> str:
        if self.result is not None:
            return "done"
        if self.interrupt is not None and self.resume is None:
            return "paused"
        return "running" if self.started_at is not None else "pending"

    @property
    def seconds(self) -> Optional[float]:
        if self.started_at is None or self.finished_at is None:
            return None
        return round(self.finished_at - self.started_at, 3)

    def to_dict(self) -> Dict[str, Any]:
        d = {k: getattr(self, k) for k in ("id", "action", "args", "after", "requires", "added_by",
                                           "attempts", "started_at", "finished_at")}
        d["result"] = self.result.to_dict() if self.result else None
        for k in ("interrupt", "resume"):  # only when used, so ordinary graph.json files don't change
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TaskSpec":
        d = dict(d)
        result = d.pop("result", None)
        spec = cls(**d)
        spec.result = NodeResult.from_dict(result) if result else None
        return spec


# (spec, store) of the node running in this thread; set by the executor.
_CURRENT_NODE: ContextVar[Optional[Tuple[TaskSpec, "GraphStore"]]] = ContextVar("agentkit_graph_node",
                                                                               default=None)


@dataclass
class GraphPatch:
    """The only way to change the graph. `link` adds (dependency, node)
    edges to nodes that haven't started yet."""

    add: List[TaskSpec] = field(default_factory=list)
    link: List[Tuple[str, str]] = field(default_factory=list)


class Planner(Protocol):
    def on_outcome(self, store: "GraphStore", spec: TaskSpec) -> Optional[GraphPatch]: ...


def _has_cycle(deps: Dict[str, List[str]]) -> bool:
    state: Dict[str, int] = {}  # 1 = visiting, 2 = done

    def visit(n: str) -> bool:
        mark = state.get(n)
        if mark == 1:
            return True
        if mark == 2:
            return False
        state[n] = 1
        if any(visit(d) for d in deps.get(n, [])):
            return True
        state[n] = 2
        return False

    return any(visit(n) for n in list(deps))


class GraphStore:
    def __init__(self, run_id: str, registry: Registry, checkpoint_path: Optional[Path] = None,
                 max_nodes: int = DEFAULT_MAX_NODES, *, channels: Optional[Dict[str, Any]] = None,
                 saver: Optional[CheckpointSaver] = None):
        self.run_id = run_id
        self.registry = registry
        self.checkpoint_path = checkpoint_path
        self.max_nodes = max_nodes
        self.specs: Dict[str, TaskSpec] = {}  # insertion order = plan order
        self.channels = ChannelState(channels)
        self.saver = saver
        self.step = 0  # outcomes (eager) or supersteps (superstep) recorded so far
        self.last_checkpoint_id: Optional[str] = None
        self.pending_outcomes: List[str] = []  # forked-in results the planner hasn't seen yet
        self._lock = threading.RLock()

    def __contains__(self, node_id: str) -> bool:
        return node_id in self.specs

    def get(self, node_id: str) -> Optional[TaskSpec]:
        return self.specs.get(node_id)

    def results(self) -> Dict[str, NodeResult]:
        with self._lock:
            return {i: s.result for i, s in self.specs.items() if s.result is not None}

    def resolved_data(self) -> Dict[str, Any]:
        return {i: r.data for i, r in self.results().items() if r.verdict == RESOLVED}

    def channel_values(self) -> Dict[str, Any]:
        with self._lock:
            return self.channels.values()

    def paused(self) -> List[TaskSpec]:
        return [s for s in self.specs.values() if s.state == "paused"]

    # ---- mutation -----------------------------------------------------------

    def apply(self, patch: GraphPatch) -> None:
        with self._lock:
            new_ids = [s.id for s in patch.add]
            if len(self.specs) + len(new_ids) > self.max_nodes:
                raise ValueError(f"patch would exceed the {self.max_nodes}-node budget")
            for spec in patch.add:
                if spec.action not in self.registry.actions:
                    raise ValueError(f"node {spec.id}: {spec.action!r} is not a registered action")
                if spec.id in self.specs or new_ids.count(spec.id) > 1:
                    raise ValueError(f"duplicate node id {spec.id!r}")
                if spec.requires not in REQUIRES:
                    raise ValueError(f"node {spec.id}: requires must be one of {REQUIRES}")
                for dep in spec.after:
                    if dep not in self.specs and dep not in new_ids:
                        raise ValueError(f"node {spec.id} depends on unknown node {dep!r}")
            for dep, node_id in patch.link:
                target = self.specs.get(node_id) or next((s for s in patch.add if s.id == node_id), None)
                if target is None or (dep not in self.specs and dep not in new_ids):
                    raise ValueError(f"link {dep}->{node_id}: unknown node")
                if target.started_at is not None or target.result is not None:
                    raise ValueError(f"link {dep}->{node_id}: {node_id} already started")

            proposed = {i: list(s.after) for i, s in self.specs.items()}
            proposed.update({s.id: list(s.after) for s in patch.add})
            for dep, node_id in patch.link:
                if dep not in proposed[node_id]:
                    proposed[node_id].append(dep)
            if _has_cycle(proposed):
                raise ValueError("patch introduces a dependency cycle")

            for spec in patch.add:
                self.specs[spec.id] = spec
            for node_id, deps in proposed.items():
                self.specs[node_id].after = deps
            self.checkpoint()

    def claim_ready(self) -> List[TaskSpec]:
        """Bypass nodes whose requirement can no longer be met, then mark
        and return every pending node whose dependencies allow it to run."""
        with self._lock:
            progressed = True
            while progressed:
                progressed = False
                for spec in self.specs.values():
                    if spec.state != "pending" or spec.requires != "resolved":
                        continue
                    deps = [self.specs[d] for d in spec.after]
                    blocking = [d for d in deps if d.result is not None and d.result.verdict != RESOLVED]
                    if blocking:
                        b = blocking[0]
                        spec.result = NodeResult(BYPASSED, reason=f"dependency {b.id} was {b.result.verdict}"
                                                 + (f": {b.result.reason}" if b.result.reason else ""))
                        spec.finished_at = time.time()
                        progressed = True
            ready = []
            for spec in self.specs.values():
                if spec.state != "pending":
                    continue
                if all(self.specs[d].result is not None for d in spec.after):
                    spec.started_at = time.time()
                    ready.append(spec)
            if ready:
                self.checkpoint()
            return ready

    def record(self, spec: TaskSpec, result: NodeResult, apply_writes: bool = True) -> None:
        """Store a node's outcome. With apply_writes (eager mode) its channel
        writes are applied at once, as a step of their own."""
        with self._lock:
            spec.result = result
            spec.finished_at = time.time()
            if apply_writes and (result.writes or self.channels):
                self.channels.apply({spec.id: result.writes} if result.writes else {})
            self.checkpoint()

    def apply_step(self, writes_by_node: Dict[str, Dict[str, Any]]) -> List[str]:
        """Superstep mode: one step's channel writes, all at once."""
        with self._lock:
            changed = self.channels.apply(writes_by_node) if (writes_by_node or self.channels) else []
            self.checkpoint()
            return changed

    def pause(self, spec: TaskSpec, value: Any) -> None:
        with self._lock:
            spec.interrupt = value
            spec.resume = None
            spec.started_at = None
            self.checkpoint()

    def resume(self, node_id: str, answer: Any) -> None:
        """Answer a paused node; continue_from() then runs it again."""
        with self._lock:
            spec = self.specs.get(node_id)
            if spec is None or spec.state != "paused":
                raise ValueError(f"node {node_id!r} is not paused")
            spec.resume = {"value": answer}
            self.checkpoint()

    def in_flight(self) -> bool:
        return any(s.state == "running" for s in self.specs.values())

    # ---- history and forks ----------------------------------------------------

    def snapshot(self, source: str, **extra: Any) -> Optional[str]:
        """Add a checkpoint to the history (no-op without a saver)."""
        if self.saver is None:
            return None
        with self._lock:
            cp = make_checkpoint(self.to_dict(), source, self.step, parent_id=self.last_checkpoint_id,
                                 run_id=self.run_id, **extra)
            self.saver.put(cp)
            self.last_checkpoint_id = cp.id
            return cp.id

    def history(self, **query: Any) -> List[Checkpoint]:
        """Newest first; see CheckpointSaver.list(before=, limit=, filter=)."""
        return self.saver.list(**query) if self.saver is not None else []

    def descendants(self, node_ids: List[str]) -> List[str]:
        children: Dict[str, List[str]] = {}
        for s in self.specs.values():
            for d in s.after:
                children.setdefault(d, []).append(s.id)
        out: List[str] = []
        stack = list(node_ids)
        while stack:
            for c in children.get(stack.pop(), []):
                if c not in out and c not in node_ids:
                    out.append(c)
                    stack.append(c)
        return out

    def fork(self, update: Dict[str, Union[NodeResult, Any]], *, from_checkpoint: Optional[str] = None,
             checkpoint_path: Optional[Path] = None, saver: Optional[CheckpointSaver] = None,
             run_id: Optional[str] = None) -> "GraphStore":
        """A new store that continues from this state (or from an earlier
        checkpoint) with the given node results replaced. Everything downstream
        of a replaced node is undone: plan nodes go back to pending, nodes the
        planner added are removed (its rules decide again). Run it with
        executor.continue_from(fork); the planner first sees the replaced
        outcomes. This store is left untouched."""
        if from_checkpoint is not None:
            cp = self.saver.get(from_checkpoint) if self.saver is not None else None
            if cp is None:
                raise KeyError(f"no checkpoint {from_checkpoint!r}")
            base = cp.graph
        else:
            base = self.to_dict()
        new = GraphStore.from_dict(base, self.registry, checkpoint_path=checkpoint_path, max_nodes=self.max_nodes,
                                   saver=saver if saver is not None else self.saver)
        if run_id:
            new.run_id = run_id
        unknown = [n for n in update if n not in new.specs]
        if unknown:
            raise KeyError(f"cannot fork: unknown node(s) {unknown}")
        for node_id in new.descendants(list(update)):
            spec = new.specs[node_id]
            if spec.added_by == "planner":
                del new.specs[node_id]
            else:
                spec.result, spec.attempts, spec.started_at, spec.finished_at = None, 0, None, None
                spec.interrupt = spec.resume = None
        for spec in new.specs.values():
            spec.after = [d for d in spec.after if d in new.specs]
        now = time.time()
        for node_id, value in update.items():
            spec = new.specs[node_id]
            spec.result = NodeResult.of(value)
            spec.interrupt = spec.resume = None
            spec.started_at = spec.started_at or now
            spec.finished_at = now
        new._rebuild_channels()
        new.pending_outcomes = list(update)
        new.last_checkpoint_id = from_checkpoint or self.last_checkpoint_id
        new.snapshot("fork", forked_from=new.last_checkpoint_id, replaced=sorted(update))
        new.checkpoint()
        return new

    def _rebuild_channels(self) -> None:
        """Channel state = the writes of the nodes that are still done, replayed
        in the order they finished (one node per step, as in eager mode)."""
        fresh = ChannelState({n: c.spec() for n, c in self.channels.channels.items()})
        done = sorted((s for s in self.specs.values() if s.result is not None and s.result.writes),
                      key=lambda s: (s.finished_at or 0.0, s.id))
        for s in done:
            fresh.apply({s.id: s.result.writes})
        self.channels = fresh

    # ---- persistence --------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            d = {"format": CHECKPOINT_FORMAT, "run_id": self.run_id,
                 "nodes": [s.to_dict() for s in self.specs.values()]}
            if self.channels:  # only runs that declare channels carry them
                d["channels"] = self.channels.to_dict()
            return d

    def checkpoint(self) -> None:
        if self.checkpoint_path:
            dump_record(self.checkpoint_path, self.to_dict())

    @classmethod
    def from_dict(cls, d: Dict[str, Any], registry: Registry, checkpoint_path: Optional[Path] = None,
                  max_nodes: int = DEFAULT_MAX_NODES, *, saver: Optional[CheckpointSaver] = None,
                  channels: Optional[Dict[str, Any]] = None) -> "GraphStore":
        if d.get("format") != CHECKPOINT_FORMAT:
            raise ValueError(f"unsupported checkpoint format {d.get('format')!r}")
        store = cls(d["run_id"], registry, checkpoint_path, max_nodes, saver=saver)
        store.channels = ChannelState.from_dict(d.get("channels"), channels)
        store.step = store.channels.step
        for n in d["nodes"]:
            spec = TaskSpec.from_dict(n)
            if spec.state == "running":  # was mid-flight when the run died
                spec.started_at = None
            store.specs[spec.id] = spec
        return store

    @classmethod
    def load(cls, path: Path, registry: Registry, max_nodes: int = DEFAULT_MAX_NODES, *,
             saver: Optional[CheckpointSaver] = None) -> "GraphStore":
        return cls.from_dict(load_record(path), registry, checkpoint_path=path, max_nodes=max_nodes, saver=saver)


class LiveGraphExecutor:
    def __init__(self, env: RunEnv, registry: Registry, planner: Optional[Planner] = None,
                 max_workers: int = 4, checkpoint_path: Optional[Path] = None,
                 max_nodes: int = DEFAULT_MAX_NODES, retry_backoff_s: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep, *, mode: str = "eager",
                 max_steps: int = DEFAULT_MAX_STEPS, channels: Optional[Dict[str, Any]] = None,
                 saver: Optional[CheckpointSaver] = None, approve_writes: bool = False,
                 rng: Optional[Callable[[], float]] = None):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.env = env
        self.registry = registry
        self.planner = planner
        self.max_workers = max_workers
        self.checkpoint_path = checkpoint_path
        self.max_nodes = max_nodes
        self.retry_backoff_s = retry_backoff_s
        self._sleep = sleep
        self.mode = mode
        self.max_steps = max_steps
        self.channels = channels
        self.saver = saver
        self.approve_writes = approve_writes
        self._rng = rng

    def run(self, run_id: str, tasks: List[TaskSpec]) -> GraphStore:
        store = GraphStore(run_id, self.registry, self.checkpoint_path, self.max_nodes, channels=self.channels,
                           saver=self.saver)
        store.apply(GraphPatch(add=tasks))
        store.snapshot("input")
        return self.continue_from(store)

    def continue_from(self, store: GraphStore) -> GraphStore:
        """Run every node that can still run. A planner exception is not
        swallowed: a broken planner should fail the run loudly (the caller
        still saves its record). Paused nodes (and what depends on them) wait;
        answer them with store.resume() and call this again."""
        if store.saver is None:
            store.saver = self.saver
        for node_id in store.pending_outcomes:  # a fork's replaced results
            self._plan(store, store.specs[node_id])
        store.pending_outcomes = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            if self.mode == "superstep":
                self._run_supersteps(store, pool)
            else:
                self._run_eager(store, pool)
        if not store.paused():
            store.channels.finish()
        store.checkpoint()
        return store

    def _submit(self, pool: ThreadPoolExecutor, spec: TaskSpec, store: GraphStore) -> Future:
        # bind_context: the worker's spans nest under this run's current span
        return pool.submit(bind_context(self._execute_traced), spec, store)

    def _run_eager(self, store: GraphStore, pool: ThreadPoolExecutor) -> None:
        running: Dict[Future, TaskSpec] = {}
        while True:
            for spec in store.claim_ready():
                running[self._submit(pool, spec, store)] = spec
            if not running:
                break
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in done:
                spec = running.pop(fut)
                outcome = fut.result()
                store.step += 1
                if isinstance(outcome, _Paused):
                    store.pause(spec, outcome.value)
                else:
                    store.record(spec, outcome)
                    self._plan(store, spec)
                store.snapshot("loop", ran=[spec.id])

    def _run_supersteps(self, store: GraphStore, pool: ThreadPoolExecutor) -> None:
        while True:
            ready = store.claim_ready()
            if not ready:
                break
            if store.step >= self.max_steps:
                for spec in ready:  # hand the claim back, so the saved graph can be continued
                    spec.started_at = None
                store.checkpoint()
                raise StepLimitExceeded(f"run needed more than {self.max_steps} steps "
                                        f"(still ready: {sorted(s.id for s in ready)})")
            futures = {self._submit(pool, spec, store): spec for spec in ready}
            wait(futures, return_when=ALL_COMPLETED)
            outcomes = sorted(((futures[f], f.result()) for f in futures), key=lambda pair: pair[0].id)
            with span("step", "superstep", step=store.step + 1, nodes=[s.id for s, _ in outcomes]):
                writes: Dict[str, Dict[str, Any]] = {}
                for spec, outcome in outcomes:
                    if isinstance(outcome, _Paused):
                        store.pause(spec, outcome.value)
                        continue
                    store.record(spec, outcome, apply_writes=False)
                    if outcome.writes:
                        writes[spec.id] = outcome.writes
                store.step += 1
                store.apply_step(writes)
                for spec, outcome in outcomes:
                    if not isinstance(outcome, _Paused):
                        self._plan(store, spec)
            store.snapshot("loop", ran=[s.id for s, _ in outcomes])

    def _plan(self, store: GraphStore, spec: TaskSpec) -> None:
        if not self.planner:
            return
        with span("step", "planner", after=spec.id) as step:
            patch = self.planner.on_outcome(store, spec)
            step.set(added=[n.id for n in (patch.add if patch else [])])
        if patch and (patch.add or patch.link):
            for new in patch.add:
                new.added_by = "planner"
            store.apply(patch)

    def _execute_traced(self, spec: TaskSpec, store: GraphStore) -> Union[NodeResult, _Paused]:
        queued_ms = round((time.time() - spec.started_at) * 1000, 3) if spec.started_at else None
        with span("node", spec.id, action=spec.action, added_by=spec.added_by, queue_wait_ms=queued_ms) as s:
            token = _CURRENT_NODE.set((spec, store))
            try:
                outcome = self._execute(spec, store)
            finally:
                _CURRENT_NODE.reset(token)
            if isinstance(outcome, _Paused):
                s.set(verdict="paused", attempts=spec.attempts, ok=True)
            else:
                s.set(verdict=outcome.verdict, attempts=spec.attempts, error_kind=outcome.error_kind,
                      ok=outcome.verdict != FAILED)
            return outcome

    def _execute(self, spec: TaskSpec, store: GraphStore) -> Union[NodeResult, _Paused]:
        action = self.registry.get_action(spec.action)
        if action.writes and self.env.dry_run:
            return self._preview(spec, action, store)
        if action.writes and self.approve_writes:
            gate = self._approval(spec, action, store)
            if gate is not None:
                return gate
        policy = policy_for(action, self.retry_backoff_s)
        logger.info("node [%s] -> %s", spec.id, spec.action)
        tries = 0
        while True:
            spec.attempts += 1
            tries += 1
            try:
                return NodeResult.of(self._call(action, spec, store))
            except ActionTimeout as e:
                return NodeResult(FAILED, reason=str(e), error_kind="timeout")
            except NodeInterrupt as pause:
                return _Paused(pause.value)
            except SeatCallFailure as e:
                if policy.should_retry(e, tries):
                    add_event("retry", attempt=tries, error_kind=e.kind)
                    self._sleep(policy.interval(tries, self._rng))
                    continue
                if e.kind in _DECLINE_KINDS:
                    return NodeResult(DECLINED, reason=f"{_DECLINE_KINDS[e.kind]}: {e}", error_kind=e.kind)
                return NodeResult(FAILED, reason=str(e), error_kind=e.kind)
            except Exception as e:  # a bug in an action: record it, keep the other branches
                if policy.should_retry(e, tries):  # only if the action's policy names this error
                    add_event("retry", attempt=tries, error_kind=type(e).__name__)
                    self._sleep(policy.interval(tries, self._rng))
                    continue
                logger.exception("node [%s] crashed", spec.id)
                return NodeResult(FAILED, reason=f"{type(e).__name__}: {e}", error_kind="internal")

    def _call(self, action: Any, spec: TaskSpec, store: GraphStore) -> Any:
        """Run one attempt of an action; with `timeout_s`, give up waiting after that long.
        A Python thread can't be killed: a timed-out attempt is abandoned (its result is
        ignored), so actions with a timeout should only read."""
        if not action.timeout_s:
            return action.fn(self.env, spec.args, store.results())
        box: Dict[str, Any] = {}
        ctx = contextvars.copy_context()  # the node, span and telemetry context go with it

        def attempt() -> None:
            try:
                box["value"] = ctx.run(action.fn, self.env, spec.args, store.results())
            except BaseException as e:  # handed back to the caller's except clauses
                box["error"] = e

        worker = threading.Thread(target=attempt, name=f"node-{spec.id}", daemon=True)
        worker.start()
        worker.join(action.timeout_s)
        if worker.is_alive():
            add_event("timeout", seconds=action.timeout_s)
            raise ActionTimeout(f"{spec.action} timed out after {action.timeout_s}s")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _approval(self, spec: TaskSpec, action: Any, store: GraphStore) -> Optional[Union[NodeResult, _Paused]]:
        """Before a real write: pause for a person with the write's preview.
        None = approved, go ahead."""
        try:
            would = action.preview(self.env, spec.args, store.results()) if action.preview else None
            answer = interrupt({"kind": "approval", "node": spec.id, "action": spec.action, "args": spec.args,
                                "would_file": would})
        except NodeInterrupt as pause:
            return _Paused(pause.value)
        except Exception as e:
            logger.exception("node [%s] approval preview crashed", spec.id)
            return NodeResult(FAILED, reason=f"approval preview {type(e).__name__}: {e}", error_kind="internal")
        if approved(answer):
            return None
        note = answer.get("note") if isinstance(answer, dict) else None
        return NodeResult(DECLINED, reason="a person did not approve this write" + (f": {note}" if note else ""),
                          data={"approval": answer})

    def _preview(self, spec: TaskSpec, action: Any, store: GraphStore) -> NodeResult:
        if action.preview is None:
            return NodeResult(DECLINED, reason="dry run: write action not executed")
        spec.attempts += 1
        try:
            would = action.preview(self.env, spec.args, store.results())
        except Exception as e:
            logger.exception("node [%s] preview crashed", spec.id)
            return NodeResult(FAILED, reason=f"preview {type(e).__name__}: {e}", error_kind="internal")
        if not would:
            return NodeResult(RESOLVED, data={"would_file": would or [], "filed": False},
                              reason="dry run: nothing to file")
        return NodeResult(HANDED_OFF, data={"would_file": would, "filed": False},
                          reason="dry run: prepared for a person, not filed")
