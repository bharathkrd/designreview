"""
Checks over a saved run folder -- the only thing grading ever reads.

A run folder holds: task.json, taskrun.json, graph.json, tool_journal.jsonl,
ground_truth_before.json, ground_truth_after.json (and stdout.txt). A check
is a pure function `(RunBundle, params) -> [CheckOutcome]`: no network, no
LLM, so a scoring bug is fixed by re-grading saved runs, never by re-running
the agent.

Statuses:
  pass   the claim matches ground truth
  fail   it doesn't (or the run broke a rule)
  drift  it matched the platform BEFORE the run but not after -- the data
         moved under the run (another team/agent), not the agent's fault
  skip   not applicable to this run
  error  ground truth couldn't be read, or the check itself crashed.
         error NEVER counts as a pass.

Built-in checks (every task gets them): run_completed, tool_calls_policy,
answer_present, tool_call_budget.

Every check has a failure mode (agentkit.registry.FAILURE_MODES) -- what kind
of mistake its failure points at. The grader counts failures by mode; the
mode never changes a score.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agentkit.record.durable_io import load_record
from agentkit.registry import Registry
from agentkit.transport.journal import JOURNAL_FILE, read_journal
from agentkit.transport.seat_rpc import is_read_tool

STATUSES = ("pass", "fail", "drift", "skip", "error")


@dataclass
class CheckOutcome:
    check: str
    name: str
    status: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown check status {self.status!r}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunBundle:
    run_dir: Path
    task: Dict[str, Any]
    taskrun: Dict[str, Any]
    graph: Optional[Dict[str, Any]]
    journal: List[Dict[str, Any]]
    before: Dict[str, Any]
    after: Dict[str, Any]
    read_only_tools: frozenset = frozenset()
    write_tools: frozenset = frozenset()  # the pack's write allowlist (extras["write_tools"])
    replay: Optional[Dict[str, Any]] = None  # replay.json, when this run is a replay (agentkit.harness.replay)

    @classmethod
    def load(cls, run_dir: Path, read_only_tools=(), write_tools=()) -> "RunBundle":
        run_dir = Path(run_dir)

        def opt(name: str) -> Any:
            p = run_dir / name
            return load_record(p) if p.exists() else None

        return cls(run_dir=run_dir, task=opt("task.json") or {}, taskrun=opt("taskrun.json") or {},
                   graph=opt("graph.json"), journal=read_journal(run_dir / JOURNAL_FILE),
                   before=opt("ground_truth_before.json") or {}, after=opt("ground_truth_after.json") or {},
                   read_only_tools=frozenset(read_only_tools), write_tools=frozenset(write_tools),
                   replay=opt("replay.json"))

    # ---- convenience -------------------------------------------------------

    @property
    def finding(self) -> Dict[str, Any]:
        return self.taskrun.get("finding") or {}

    @property
    def answer(self) -> str:
        return self.taskrun.get("claimed_answer") or ""

    @property
    def dry_run(self) -> bool:
        return bool(self.taskrun.get("dry_run", True))

    def obs(self, phase: str, key: str) -> Optional[Dict[str, Any]]:
        src = self.before if phase == "before" else self.after
        return (src.get("observations") or {}).get(key)

    def truth(self, phase: str, key: str) -> Any:
        """The observed value, or None if the observation failed/was missing."""
        o = self.obs(phase, key)
        return o.get("value") if o and "value" in o else None

    def obs_error(self, phase: str, key: str) -> Optional[str]:
        o = self.obs(phase, key)
        if o is None:
            return "not observed"
        return o.get("error_kind")

    def tools_called(self) -> List[str]:
        return [e.get("tool") for e in self.journal if e.get("tool")]

    def steps(self) -> List[Dict[str, Any]]:
        return list(self.taskrun.get("steps") or [])


# ---------------------------------------------------------------- built-in checks

def check_run_completed(b: RunBundle, _p: Dict[str, Any]) -> List[CheckOutcome]:
    ended = b.taskrun.get("ended")
    if not b.taskrun:
        return [CheckOutcome("run_completed", "ended", "fail", "no taskrun.json was written")]
    if ended == "done":
        return [CheckOutcome("run_completed", "ended", "pass", "run ended done")]
    if ended == "running":
        return [CheckOutcome("run_completed", "ended", "fail", "record still says running: the run crashed")]
    return [CheckOutcome("run_completed", "ended", "fail", f"ended={ended}: {b.taskrun.get('error')}")]


def check_tool_calls_policy(b: RunBundle, _p: Dict[str, Any]) -> List[CheckOutcome]:
    """From the transport journal, not the agent's report: a dry run may only
    read; a write run may only write through the pack's write allowlist."""
    tools = b.tools_called()
    writes = sorted({t for t in tools if not is_read_tool(t, b.read_only_tools)})
    if b.dry_run and writes:
        return [CheckOutcome("tool_calls_policy", "tools", "fail", f"dry run called write tools: {', '.join(writes)}")]
    outside = [t for t in writes if t not in b.write_tools]
    if not b.dry_run and outside:
        return [CheckOutcome("tool_calls_policy", "tools", "fail",
                             f"write run called tools outside the pack's write allowlist: {', '.join(outside)}")]
    mode = "dry run" if b.dry_run else "write mode"
    return [CheckOutcome("tool_calls_policy", "tools", "pass",
                         f"{mode}: {len(tools)} call(s); writes: {', '.join(writes) or 'none'}")]


def check_answer_present(b: RunBundle, _p: Dict[str, Any]) -> List[CheckOutcome]:
    if not b.answer.strip():
        return [CheckOutcome("answer_present", "answer", "fail", "no answer text")]
    src = b.taskrun.get("answer_source")
    return [CheckOutcome("answer_present", "answer", "pass", f"{len(b.answer)} chars, source={src}")]


def check_tool_call_budget(b: RunBundle, _p: Dict[str, Any]) -> List[CheckOutcome]:
    """No wasted reads: the same read (tool + arguments) may succeed only once,
    unless a write happened in between (the state may have changed, so a
    re-read is right). A failed call retried with the same arguments is fine.
    In a replay only the replay's own calls count: its journal starts with the
    original run's calls, which the original run was graded on."""
    start = (b.replay or {}).get("replay_start_seq") or 0
    seen, repeated = set(), []
    for e in (e for e in b.journal if (e.get("seq") or 0) >= start):
        tool = e.get("tool")
        if not tool:
            continue
        if not is_read_tool(tool, b.read_only_tools):
            seen.clear()  # after a write, a fresh read is not waste
            continue
        if not e.get("ok"):
            continue
        key = (tool, json.dumps(e.get("args") or {}, sort_keys=True, default=str))
        if key in seen:
            repeated.append(tool)
        seen.add(key)
    if repeated:
        return [CheckOutcome("tool_call_budget", "repeated_reads", "fail",
                             f"identical read(s) repeated: {', '.join(sorted(set(repeated)))}")]
    return [CheckOutcome("tool_call_budget", "repeated_reads", "pass",
                         f"{len(b.tools_called())} call(s), no identical read repeated")]


BUILTIN_CHECKS: Dict[str, Callable[[RunBundle, Dict[str, Any]], List[CheckOutcome]]] = {
    "run_completed": check_run_completed,
    "tool_calls_policy": check_tool_calls_policy,
    "answer_present": check_answer_present,
    "tool_call_budget": check_tool_call_budget,
}
BUILTIN_FAILURE_MODES: Dict[str, str] = {
    "run_completed": "premature_stop",
    "tool_calls_policy": "policy_breach",
    "answer_present": "premature_stop",
    "tool_call_budget": "inefficiency",
}


def failure_mode_of(check: str, registry: Registry) -> str:
    """The failure mode of a built-in or pack check ("" if the pack gave none)."""
    if check in BUILTIN_FAILURE_MODES:
        return BUILTIN_FAILURE_MODES[check]
    spec = registry.checks.get(check)
    return getattr(spec, "failure_mode", "") if spec else ""


def specs_for(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"name": n, "params": {}} for n in BUILTIN_CHECKS] + list(task.get("verifiers") or [])


def check_run(bundle: RunBundle, registry: Registry) -> List[CheckOutcome]:
    """Every check for one saved run. A crashing check is recorded as an
    error on that check; it never hides the others."""
    out: List[CheckOutcome] = []
    for spec in specs_for(bundle.task):
        name, params = spec["name"], spec.get("params") or {}
        fn = BUILTIN_CHECKS.get(name) or (registry.checks[name].check if name in registry.checks else None)
        if fn is None:
            out.append(CheckOutcome(name, "config", "error", "unknown verifier"))
            continue
        try:
            out += fn(bundle, params)
        except Exception as e:
            out.append(CheckOutcome(name, "checker", "error", f"check crashed: {type(e).__name__}: {e}"))
    return out
