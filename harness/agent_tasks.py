"""
Run Team 21's real agent on the server: the design-review tasks of this instance, graded by our own verifiers.

harness/runner.py calls run_agent_tasks(instance, record) after its platform smoke checks. For the instance:

  1. the pack's tasks whose `tenants` include it (Suryodaya: 8, Keystone: 4) run as one agentkit batch --
     each task in its own subprocess, as a dry run (nothing is written), with the platform LLM when
     OPENAI_API_KEY is set (else template answers);
  2. the harness reads the platform's ground truth before and after each run with its own login (the runner's
     injected token on the server) and grades every run from its saved files;
  3. each task becomes one results.json entry (passed = the task passed; score = its partial credit), and each
     check that applied becomes one more entry (a skipped check is not reported: only what ran is a result).

Failures are reported, never hidden: a check that ends "fail", "error" or "drift" is passed=false with its
detail as evidence; a task whose agent crashed or whose files are missing is passed=false; an exception in this
module becomes one passed=false entry with the exception and the line it came from.

`sim` (a fixtures folder) replays the captured platform instead -- offline, template answers -- so CI can run
the same code path on every push.
"""

from __future__ import annotations

import datetime as dt
import os
import traceback
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_ENTRIES = 200  # the results.json limit of the official harness (1 to 200 tasks)
FAILED_STATUSES = {"fail", "error", "drift"}

Record = Callable[..., None]  # record(task_id, title, passed, evidence, score=None)


def _short(text: Any, n: int = 300) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= n else s[: n - 3] + "..."


def _where(exc: BaseException) -> str:
    """The exception and the file:line it came from (the last frame inside this repository)."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if str(PROJECT_ROOT) in f.filename] or \
        traceback.extract_tb(exc.__traceback__)
    if not frames:
        return f"{type(exc).__name__}: {exc}"
    f = frames[-1]
    path = Path(f.filename)
    try:
        path = path.relative_to(PROJECT_ROOT)
    except ValueError:
        pass
    return f"{type(exc).__name__}: {exc} (at {path.as_posix()}:{f.lineno})"


def _task_evidence(score: Optional[Dict[str, Any]], taskrun: Optional[Dict[str, Any]]) -> str:
    if score is None:
        return "not graded: the run left no score (crashed or missing run files)"
    checks = score.get("checks") or []
    applied = [c for c in checks if c.get("status") != "skip"]
    bad = [c for c in applied if c.get("status") in FAILED_STATUSES]
    parts = [f"{score.get('status')}; {len(applied) - len(bad)}/{len(applied)} checks passed"]
    for c in bad[:4]:
        parts.append(f"{c.get('check')}.{c.get('name')}={c.get('status')}: {_short(c.get('detail'), 140)}")
    if taskrun:
        narrate = next((s.get("detail") or {} for s in taskrun.get("steps") or [] if s.get("kind") == "narrate"), {})
        source = taskrun.get("answer_source") or "none"
        model = narrate.get("model")
        parts.append(f"answer={source}" + (f" ({narrate.get('provider')}:{model})" if model else ""))
        if taskrun.get("route"):
            parts.append(f"routed={taskrun['route'].get('plan')}")
    return "; ".join(parts)


def _read(path: Path) -> Optional[Dict[str, Any]]:
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def entries_for(instance: str, results: List[Any], runs_dir: Path, tasks_by_id: Dict[str, Any],
                room: int) -> List[Dict[str, Any]]:
    """results.json entries (without the instance prefix) for graded runs: one per task, one per applied
    check. With less room than that, passing checks of passing tasks are left out first (their task entry
    still says how many passed)."""
    task_rows, check_rows = [], []
    for entry, score in results:
        task_id = entry.get("task_id")
        task = tasks_by_id.get(task_id)
        title = f"Agent task {task_id}: {_short(getattr(task, 'prompt', '') or task_id, 120)}"
        taskrun = _read(runs_dir / str(entry.get("run_id")) / "taskrun.json")
        passed = bool(score) and score.get("status") == "pass"
        try:
            partial = float(Fraction(str(score.get("partial", "0")))) if score else 0.0
        except (ValueError, ZeroDivisionError):
            partial = 0.0
        task_rows.append({"id": f"task:{task_id}", "title": title, "passed": passed,
                          "score": 1.0 if passed else round(partial, 4),
                          "evidence": _task_evidence(score, taskrun)})
        for c in (score or {}).get("checks") or []:
            if c.get("status") == "skip":
                continue
            ok = c.get("status") == "pass"
            check_rows.append(({"id": f"check:{task_id}:{c.get('check')}:{c.get('name')}",
                                "title": f"{task_id}: check {c.get('check')} ({c.get('name')})",
                                "passed": ok, "score": 1.0 if ok else 0.0,
                                "evidence": f"{c.get('status')}: {_short(c.get('detail'), 280)}"}, passed and ok))
    rows = list(task_rows)
    keep = [r for r, routine in check_rows if not routine]  # failures, and checks of failed tasks, first
    routine = [r for r, is_routine in check_rows if is_routine]
    rows += keep[: max(0, room - len(rows))]
    rows += routine[: max(0, room - len(rows))]
    return rows


def run_agent_tasks(instance: str, record: Record, *, sim: Optional[Path] = None, faults: Optional[List[str]] = None,
                    room: int = MAX_ENTRIES, runs_dir: Optional[Path] = None) -> None:
    """Run and grade this instance's tasks; report them through `record`. Never raises.
    `faults` (sim only) are agentkit.sim faults, e.g. to show that a broken read is reported as a failure."""
    try:
        from agentkit.config import load_env
        from agentkit.harness.batch import SimSession, run_batch
        from agentkit.harness.grade import grade_batch
        from agentkit.harness.tasks import load_tasks
        from agentkit.registry import load_pack

        load_env()
        registry = load_pack("packs.designreview")
        tasks = [t for t in load_tasks([registry.extras["tasks_dir"]]) if instance in t.tenants]
        if not tasks:
            record("agent_tasks", "Agent tasks for this instance", False, f"no task lists tenant {instance!r}")
            return
        runs_dir = runs_dir or PROJECT_ROOT / "runs"
        skip_llm = sim is not None or not os.environ.get("OPENAI_API_KEY")
        stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        kwargs: Dict[str, Any] = {}
        if sim is not None:
            session = SimSession(Path(sim), list(faults or []), registry.read_only)
            kwargs = {"reader_factory": session.reader_for, "agent_runner": session.run_agent,
                      "fresh_reader_per_task": True}
        print(f"=== Agent tasks on {instance}: {len(tasks)} task(s), "
              f"{'template answers' if skip_llm else 'platform LLM'}{', sim' if sim else ''} ===", flush=True)
        batch_dir = run_batch(tasks, tenant_override=instance, skip_llm=skip_llm, runs_dir=runs_dir,
                              batch_id=f"server-{instance}-{stamp}", **kwargs)
        _, results = grade_batch(batch_dir)
        by_id = {t.id: t for t in tasks}
        graded = {e.get("task_id") for e, _ in results}
        rows = entries_for(instance, results, runs_dir, by_id, room)
        for t in tasks:  # a task the batch never recorded is a failure too
            if t.id not in graded:
                rows.insert(0, {"id": f"task:{t.id}", "title": f"Agent task {t.id}", "passed": False, "score": 0.0,
                                "evidence": "the batch has no run for this task"})
        for r in rows[:room]:
            record(r["id"], r["title"], r["passed"], r["evidence"], score=r["score"])
    except Exception as exc:  # one broken step must not lose the other results
        record("agent_tasks", "Agent tasks for this instance", False, _where(exc))
