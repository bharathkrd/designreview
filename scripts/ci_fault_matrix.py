"""
Fault-injection matrix: does the system degrade the way it should?

    python scripts/ci_fault_matrix.py [--scenarios packs/designreview/ci_faults.toml]
                                      [--fixtures packs/designreview/fixtures] [--runs-dir runs]

For each scenario in the TOML file: replay one task on the captured fixtures with the
scenario's faults injected by the simulated platform (template answers, offline), grade
it, and compare with what the scenario expects:
  - the agent run finished (ended = "done") -- a fault may lower the grade, never crash the agent;
  - the run's overall grade (pass / drift / fail) is the expected one;
  - every check listed in expect_checks ended with exactly that status.
Each scenario is its own batch (runs/batches/<prefix>-<n>), so the evidence stays on disk.
A Markdown table goes to stdout and, in GitHub Actions, to the job summary.
Exit 1 if any scenario differs from its expectation.

Domain-free: the scenarios (task ids, tool names, texts) are pack data.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, ConfigDict, Field, ValidationError  # noqa: E402

from agentkit.config import ConfigError, read_config, validation_message  # noqa: E402

STATUSES = ("pass", "drift", "fail")


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    task: str = Field(min_length=1)
    faults: List[str] = Field(min_length=1)
    expect: str
    why: str = ""
    expect_checks: Dict[str, str] = Field(default_factory=dict)


class Matrix(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: List[Scenario] = Field(min_length=1)


def load_matrix(path: Path) -> List[Scenario]:
    try:
        scenarios = Matrix.model_validate(read_config(path)).scenario
    except ValidationError as e:
        raise ConfigError(validation_message(e, str(path))) from None
    for s in scenarios:
        bad = [v for v in [s.expect, *s.expect_checks.values()] if v not in STATUSES + ("skip", "error")]
        if bad or s.expect not in STATUSES:
            raise ConfigError(f"{path}: scenario {s.name!r}: unknown status {bad or s.expect!r}")
    return scenarios


def run_scenario(n: int, s: Scenario, tasks: Dict[str, object], fixtures: Path, runs_dir: Path,
                 prefix: str, read_only) -> Dict[str, object]:
    from agentkit.harness.batch import SimSession, run_batch
    from agentkit.harness.grade import grade_batch
    from agentkit.record.durable_io import load_record

    if s.task not in tasks:
        return {"scenario": s, "ok": False, "got": "—", "problems": [f"unknown task {s.task!r}"]}
    sim = SimSession(fixtures, s.faults, read_only)
    batch_dir = run_batch([tasks[s.task]], skip_llm=True, runs_dir=runs_dir, reader_factory=sim.reader_for,
                          agent_runner=sim.run_agent, fresh_reader_per_task=True, batch_id=f"{prefix}-{n}")
    _, results = grade_batch(batch_dir)
    problems: List[str] = []
    got = "—"
    for entry, score in results:
        if score is None:
            problems.append(f"run not graded ({entry.get('status')}: {entry.get('reason', '')})")
            continue
        got = score["status"]
        taskrun = load_record(runs_dir / entry["run_id"] / "taskrun.json")
        if taskrun.get("ended") != "done":
            problems.append(f"agent run ended {taskrun.get('ended')!r}: {taskrun.get('error')}")
        if got != s.expect:
            problems.append(f"graded {got}, expected {s.expect}")
        by_check: Dict[str, set] = {}
        for c in score["checks"]:
            by_check.setdefault(c["check"], set()).add(c["status"])
        for check, want in s.expect_checks.items():
            seen = by_check.get(check)
            if not seen:
                problems.append(f"check {check} did not run")
            elif want not in seen:
                problems.append(f"check {check} was {sorted(seen)}, expected {want}")
    return {"scenario": s, "ok": not problems, "got": got, "problems": problems}


def render(rows: List[Dict[str, object]]) -> str:
    lines = ["## Fault-injection matrix", "",
             "| Scenario | Task | Faults | Expected | Graded | Result |", "|---|---|---|---|---|---|"]
    for r in rows:
        s: Scenario = r["scenario"]  # type: ignore[assignment]
        faults = "<br>".join(f"`{f}`" for f in s.faults)
        result = "ok" if r["ok"] else "**MISMATCH**: " + "; ".join(r["problems"])  # type: ignore[arg-type]
        lines.append(f"| {s.name} | `{s.task}` | {faults} | {s.expect} | {r['got']} | {result} |")
    passed = sum(1 for r in rows if r["ok"])
    lines += ["", f"**{passed} of {len(rows)} fault scenarios behave as expected.**", ""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay tasks with injected faults and check how they are graded.")
    ap.add_argument("--scenarios", type=Path, default=ROOT / "packs/designreview/ci_faults.toml")
    ap.add_argument("--fixtures", type=Path, default=ROOT / "packs/designreview/fixtures")
    ap.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    ap.add_argument("--batch-prefix", default="ci-fault")
    ap.add_argument("--pack", default=None, help="default: config/project.toml default_pack")
    args = ap.parse_args(argv)

    from agentkit.config import default_pack
    from agentkit.harness.tasks import load_tasks
    from agentkit.registry import load_pack

    scenarios = load_matrix(args.scenarios)
    registry = load_pack(args.pack or default_pack())
    tasks = {t.id: t for t in load_tasks([Path(registry.extras["tasks_dir"])])}
    rows = [run_scenario(n, s, tasks, args.fixtures, args.runs_dir, args.batch_prefix, registry.read_only)
            for n, s in enumerate(scenarios, 1)]
    report = render(rows)
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
