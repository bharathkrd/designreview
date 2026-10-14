"""
Cost against accuracy for several graded batches: one row for each batch ("arm"), and the arms that no
other arm beats on both (the Pareto frontier).

    python -m agentkit.harness.pareto runs/batches/<a> runs/batches/<b> ... [--out report.md]

Each arm is one graded batch, for example the same tasks with a different first LLM provider, or with
template answers only (`--skip-llm`, the $0 baseline). For each arm, from the saved files only:

  runs, passed       score.json of each run (a missing score counts as not passed)
  pass rate          passed / runs, with a 95% Wilson interval
  partial            the mean partial credit (score.json "partial")
  answers            where the final answers came from: llm / template (taskrun.json answer_source)
  escalated          runs with LLM calls on more than one model (a rejected or cut-off cheap draft)
  cost               the sum of llm_ledger.json cost_usd_estimated; cost per passed run
  seconds            the mean run time (taskrun.json seconds)
  models             the provider:model of each LLM call, with counts

An arm is on the frontier when no other arm has a pass rate at least as high and a cost at least as low,
with one of the two strictly better. Report only: it never changes a score. Small samples give wide
intervals; the interval column says how wide.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentkit.harness.grade import wilson_interval


@dataclass
class Arm:
    batch_id: str
    skip_llm: bool
    runs: int = 0
    passed: int = 0
    partial_sum: Fraction = Fraction(0)
    sources: Counter = field(default_factory=Counter)
    escalated: int = 0
    cost: float = 0.0
    seconds: List[float] = field(default_factory=list)
    models: Counter = field(default_factory=Counter)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.runs if self.runs else 0.0

    @property
    def label(self) -> str:
        if self.skip_llm or not self.models:
            return "template only (no LLM)"
        return self.models.most_common(1)[0][0]

    @property
    def cost_per_pass(self) -> Optional[float]:
        return self.cost / self.passed if self.passed else None


def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_arm(batch_dir: Path) -> Arm:
    manifest = _read(batch_dir / "manifest.json")
    if manifest is None:
        raise ValueError(f"{batch_dir}: no readable manifest.json")
    runs_root = batch_dir.parent.parent
    arm = Arm(batch_id=str(manifest.get("batch_id") or batch_dir.name), skip_llm=bool(manifest.get("skip_llm")))
    for entry in manifest.get("runs") or []:
        run_dir = runs_root / str(entry.get("run_id"))
        arm.runs += 1
        score = _read(run_dir / "score.json") or {}
        if score.get("status") == "pass":
            arm.passed += 1
        try:
            arm.partial_sum += Fraction(str(score.get("partial", "0")))
        except (ValueError, ZeroDivisionError):
            pass
        taskrun = _read(run_dir / "taskrun.json") or {}
        arm.sources[taskrun.get("answer_source") or "none"] += 1
        if isinstance(taskrun.get("seconds"), (int, float)):
            arm.seconds.append(float(taskrun["seconds"]))
        ledger = _read(run_dir / "llm_ledger.json") or {}
        arm.cost += float((ledger.get("summary") or {}).get("cost_usd_estimated") or 0.0)
        calls = [f"{c.get('provider')}:{c.get('model')}" for c in ledger.get("calls") or []]
        arm.models.update(calls)
        if len(set(calls)) > 1:
            arm.escalated += 1
    return arm


def frontier(arms: List[Arm]) -> List[bool]:
    """True for each arm that no other arm beats on pass rate and cost together."""
    out = []
    for a in arms:
        beaten = any(b is not a and b.pass_rate >= a.pass_rate and b.cost <= a.cost
                     and (b.pass_rate > a.pass_rate or b.cost < a.cost) for b in arms)
        out.append(not beaten)
    return out


def render(arms: List[Arm]) -> str:
    on = frontier(arms)
    lines = ["| Arm (main model) | Batch | Runs | Passed | Pass rate (95% CI) | Partial | Answers llm / template "
             "| Escalated | Cost $ | $ per pass | Mean s | Frontier |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    order = sorted(range(len(arms)), key=lambda i: (arms[i].cost, -arms[i].pass_rate))
    for i in order:
        a = arms[i]
        lo, hi = wilson_interval(a.passed, a.runs) if a.runs else (0.0, 0.0)
        partial = float(a.partial_sum / a.runs) if a.runs else 0.0
        cpp = "—" if a.cost_per_pass is None else f"{a.cost_per_pass:.4f}"
        secs = f"{sum(a.seconds) / len(a.seconds):.1f}" if a.seconds else "—"
        lines.append(f"| {a.label} | `{a.batch_id}` | {a.runs} | {a.passed} | {a.pass_rate:.2f} ({lo:.2f}–{hi:.2f}) "
                     f"| {partial:.2f} | {a.sources.get('llm', 0)} / {a.sources.get('template', 0)} | {a.escalated} "
                     f"| {a.cost:.4f} | {cpp} | {secs} | {'yes' if on[i] else ''} |")
    lines += ["", "Models of each LLM call:", ""]
    for i in order:
        a = arms[i]
        used = ", ".join(f"{m} ({n})" for m, n in a.models.most_common()) or "none"
        lines.append(f"- `{a.batch_id}`: {used}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Cost against accuracy for several graded batches.")
    ap.add_argument("batches", nargs="+", type=Path, help="graded batch folders (runs/batches/<id>)")
    ap.add_argument("--out", type=Path, help="also write the table to this Markdown file")
    args = ap.parse_args(argv)
    try:
        arms = [load_arm(b) for b in args.batches]
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    text = render(arms)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
