"""
Grade saved runs. Files only -- no network, no agent, no LLM.

    python -m agentkit.harness.grade runs/batches/<batch_id>
    python -m agentkit.harness.grade runs/<run_id> [runs/<run_id> ...]

    python -m agentkit.harness.grade --check runs/batches/<batch_id>

Each run gets runs/<run_id>/score.json; a batch also gets batch_score.json
and report.md beside its manifest. Re-grading an old batch uses the current
checks against the same saved evidence. Run status: fail if any check failed
or errored; drift if the only mismatches are data that moved during the run;
else pass. Exit code 1 if any run failed.

Batch level (pass^k): a task passes only if EVERY run of it passed -- every
tenant, every repeat. A run that crashed, never wrote taskrun.json, hit a
harness error, or is missing from the manifest altogether counts as a failed
run. report.md states the result as "**P of T tasks pass on every run.**"
(the line CI checks for). batch_score.json holds the same numbers with no
timestamps, so it is byte-stable across re-grades.

Reliability (report and batch_score.json; never part of pass/fail):
- per task, for k = 1..n (n runs expected, c passed):
    pass@k = 1 - C(n-c, k) / C(n, k)   at least one of k runs passes ("can do it")
    pass^k = C(c, k) / C(n, k)         all k runs pass ("does it reliably")
  unbiased estimators, kept as exact fractions ("1/3") so the file stays byte-stable;
- a 95% Wilson interval for the share of tasks that pass every run (9 of 9
  only says the true rate is probably above 0.70);
- the run pass rate with a standard error clustered by task (runs of one task
  are correlated, so the plain standard error would be too small).
Per run, score.json also has `partial` = 0.5 * passed/applicable + 0.5 * (run
passed) -- partial credit over the checks that applied (pass/fail/error) --
and `fail_modes`, failed checks counted by failure mode.

--check re-grades in memory, writes nothing, and compares with the saved
score.json files and batch_score.json: exit 0 if identical, 1 otherwise
(including a batch that was never graded). This is how CI proves grading is
deterministic.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agentkit.harness.checks import CheckOutcome, RunBundle, check_run, failure_mode_of
from agentkit.config import default_pack
from agentkit.record.durable_io import dump_record, durable_write_text, load_record
from agentkit.registry import Registry, load_pack
from agentkit.telemetry import load_telemetry

SCORER_VERSION = "agentkit-grade-v2"  # v2: reliability curves, intervals, partial credit, failure modes
WILSON_Z = 1.96  # 95%
BATCH_SCORE_FILE = "batch_score.json"


def overall_status(checks: List[CheckOutcome]) -> str:
    statuses = {c.status for c in checks}
    if statuses & {"fail", "error"}:
        return "fail"
    if "drift" in statuses:
        return "drift"
    return "pass"


# ---------------------------------------------------------------- statistics

def frac(x: Fraction) -> str:
    """An exact fraction as text: "1/3", "1", "0"."""
    return str(Fraction(x))


def pass_at_k(n: int, c: int, k: int) -> Fraction:
    """Probability that at least one of k runs, drawn without replacement from
    n runs of which c passed, passes (unbiased estimator)."""
    if not 1 <= k <= n:
        raise ValueError(f"k must be in 1..{n}, got {k}")
    return 1 - Fraction(math.comb(n - c, k), math.comb(n, k))


def pass_hat_k(n: int, c: int, k: int) -> Fraction:
    """Probability that all k runs, drawn without replacement from n runs of
    which c passed, pass (the reliability measure pass^k)."""
    if not 1 <= k <= n:
        raise ValueError(f"k must be in 1..{n}, got {k}")
    return Fraction(math.comb(c, k), math.comb(n, k))


def wilson_interval(x: int, n: int, z: float = WILSON_Z) -> Tuple[float, float]:
    """Wilson score interval for x successes out of n (good for small n and
    for x = 0 or x = n, where the normal approximation breaks down)."""
    if n <= 0:
        return 0.0, 1.0
    p = x / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def clustered_se(clusters: List[List[int]]) -> float:
    """Standard error of the mean of 0/1 scores, clustered: scores in one
    cluster (the runs of one task) are not independent.
    SE = sqrt(sum over clusters of (sum of (s - mean))^2) / n."""
    scores = [s for c in clusters for s in c]
    if not scores:
        return 0.0
    mean = sum(scores) / len(scores)
    return math.sqrt(sum(sum(s - mean for s in c) ** 2 for c in clusters)) / len(scores)


def partial_score(passed: int, applicable: int, full: bool) -> Fraction:
    """Partial credit: half for the share of applicable checks passed, half for
    passing outright."""
    share = Fraction(passed, applicable) if applicable else Fraction(int(full))
    return Fraction(1, 2) * share + Fraction(1, 2) * int(full)


def _4(x: float) -> str:
    return f"{x:.4f}"


def grade_run(run_dir: Path, registry: Optional[Registry] = None, *, write: bool = True) -> Dict:
    run_dir = Path(run_dir)
    task = load_record(run_dir / "task.json") if (run_dir / "task.json").exists() else {}
    registry = registry or load_pack(task.get("pack") or default_pack())
    bundle = RunBundle.load(run_dir, read_only_tools=registry.read_only,
                            write_tools=registry.extras.get("write_tools", ()))
    checks = check_run(bundle, registry)
    status = overall_status(checks)
    applicable = [c for c in checks if c.status in ("pass", "fail", "error")]
    failed = [c for c in checks if c.status in ("fail", "error")]
    score = {
        "scorer": SCORER_VERSION,
        "run_id": bundle.taskrun.get("run_id") or run_dir.name,
        "task_id": task.get("id"),
        "tenant": bundle.taskrun.get("tenant"),
        "status": status,
        "counts": dict(Counter(c.status for c in checks)),
        "partial": frac(partial_score(sum(c.status == "pass" for c in applicable), len(applicable),
                                      status == "pass")),
        "fail_modes": dict(sorted(Counter(failure_mode_of(c.check, registry) or "untagged"
                                          for c in failed).items())),
        "checks": [c.to_dict() for c in checks],
    }
    if write:
        dump_record(run_dir / "score.json", score)
    return score


def render_batch_report(batch_dir: Path, manifest: Dict, results: List[Tuple[Dict, Optional[Dict]]],
                        batch_score: Optional[Dict] = None) -> Path:
    batch_score = batch_score or score_batch(manifest, results)
    totals = Counter((s["status"] if s else e.get("status", "missing")) for e, s in results)
    lines = [
        f"# Harness batch {manifest.get('batch_id')}",
        "",
        f"- Mode: {'write' if manifest.get('write') else 'dry run'}; LLM {'on' if not manifest.get('skip_llm') else 'off (template answers)'}",
        f"- Graded {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} by {SCORER_VERSION}",
        "- Totals: " + ", ".join(f"{k} {v}" for k, v in sorted(totals.items())),
        "",
        f"**{batch_score['total']['tasks_passing_all']} of {batch_score['total']['tasks']} tasks pass on every run.**"
        + (f" ({manifest['repeat']} runs per task and tenant.)" if manifest.get("repeat", 1) > 1 else ""),
        "",
        _interval_line(batch_score["total"]),
        "",
        "| Task | Tenant | Status | Checks | Partial credit |",
        "|---|---|---|---|---|",
    ]
    for entry, score in results:
        if score is None:
            lines.append(f"| `{entry.get('task_id')}` | {entry.get('tenant')}{_repeat_label(entry, manifest)} | "
                         f"{entry.get('status', 'missing')} | "
                         f"{entry.get('reason', '')} | 0.00 |")
        else:
            counts = ", ".join(f"{k} {v}" for k, v in sorted(score["counts"].items()))
            lines.append(f"| `{entry.get('task_id')}` | {entry.get('tenant')}{_repeat_label(entry, manifest)} | "
                         f"**{score['status']}** | {counts} | {_dec(score.get('partial', '0'))} |")
    problems = [(e, s) for e, s in results if s and s["status"] != "pass"]
    if problems:
        lines += ["", "## Checks that did not pass", ""]
        for entry, score in problems:
            lines += [f"### `{entry.get('task_id')}` / {entry.get('tenant')} ({score['status']})", ""]
            for c in score["checks"]:
                if c["status"] not in ("pass", "skip"):
                    lines.append(f"- **{c['status']}** `{c['check']}` / {c['name']}: {c['detail']}")
            lines.append("")
    lines += _reliability_section(batch_score)
    lines += _failure_mode_section(results)
    lines += _performance_section(batch_dir, manifest, results)
    unrun = {t: e for t, e in batch_score["tasks"].items() if e["missing"]}
    if unrun:
        lines += ["", "## Runs that never happened", ""]
        lines += [f"- `{t}`: {e['missing']} of {e['expected']} expected run(s) missing from the manifest"
                  for t, e in unrun.items()]
    path = batch_dir / "report.md"
    durable_write_text(path, "\n".join(lines) + "\n")
    return path


def _dec(fraction_text: str) -> str:
    return f"{float(Fraction(fraction_text)):.2f}"


def _interval_line(total: Dict) -> str:
    lo, hi = total["tasks_passing_all_wilson95"]
    return (f"95% interval for the share of tasks that pass every run: {lo} to {hi} (Wilson, {total['tasks']} "
            f"tasks). Run pass rate {_dec(total['run_pass_rate'])} ± {total['run_pass_rate_se_clustered']} "
            f"(standard error clustered by task, {total['runs']} runs).")


def _reliability_section(batch_score: Dict) -> List[str]:
    """pass@1, pass@n and pass^n per task (n = that task's runs); a table only
    when tasks ran more than once."""
    tasks = batch_score["tasks"]
    if max((len(r.get("pass_hat_k") or {}) for r in tasks.values()), default=0) < 2:
        return []
    rows = []
    for task_id, r in tasks.items():
        n = str(len(r.get("pass_hat_k") or {}))
        if n != "0":
            rows.append(f"| `{task_id}` | {n} | {r['passed']} | {r['pass_at_k']['1']} | {r['pass_at_k'][n]} | "
                        f"{r['pass_hat_k'][n]} |")
    mean = batch_score["total"]["pass_hat_k_mean"]
    return ["", "## Reliability", "",
            "pass@k: at least one of k runs passes. pass^k: all k runs pass. n = the task's runs. "
            "A task with pass@n = 1 but pass^n < 1 can do the job, but not reliably.", "",
            "| Task | n | Passed | pass@1 | pass@n | pass^n |", "|---|---|---|---|---|---|", *rows, "",
            "Mean pass^k over tasks: " + ", ".join(f"k={k}: {_dec(v)}" for k, v in mean.items())]


def _failure_mode_section(results: List[Tuple[Dict, Optional[Dict]]]) -> List[str]:
    modes: Counter = Counter()
    for _entry, score in results:
        if score:
            modes.update(score.get("fail_modes") or {})
    if not modes:
        return []
    return ["", "## Failures by mode", "", "| Mode | Failed checks |", "|---|---|",
            *[f"| {m} | {n} |" for m, n in sorted(modes.items(), key=lambda kv: (-kv[1], kv[0]))]]


def _ms(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.0f}"


def _performance_section(batch_dir: Path, manifest: Dict, results: List[Tuple[Dict, Optional[Dict]]]) -> List[str]:
    """Timings, calls and tokens per run from telemetry.json / llm_ledger.json.
    Report-only: timings differ run to run, so none of this is in batch_score.json."""
    runs_root = batch_dir.parent.parent
    rows: List[str] = []
    for entry, _ in results:
        run_dir = runs_root / str(entry.get("run_id"))
        tel = load_telemetry(run_dir) if run_dir.exists() else None
        if not tel:
            continue
        by_kind = tel["summary"]["by_kind"]
        tool, node = by_kind.get("tool") or {}, by_kind.get("node") or {}
        root = (tel.get("tree") or [{}])[0]
        llm = tel["summary"]["llm"]
        ledger = load_record(run_dir / "llm_ledger.json") if (run_dir / "llm_ledger.json").exists() else {}
        cost = (ledger.get("summary") or {}).get("cost_usd_estimated")
        rows.append(f"| `{entry.get('task_id')}` | {entry.get('tenant')}{_repeat_label(entry, manifest)} | "
                    f"{_ms(root.get('duration_ms'))} | {node.get('count', 0)} | {tool.get('count', 0)} | "
                    f"{_ms(tool.get('p50_ms'))} / {_ms(tool.get('p95_ms'))} | {llm['calls']} | "
                    f"{llm['input_tokens']} / {llm['output_tokens']} | {'—' if cost is None else f'{cost:.4f}'} |")
    if not rows:
        return []
    return ["", "## Performance", "",
            "From each run's telemetry.json (not graded; timings vary between runs).", "",
            "| Task | Tenant | Run ms | Nodes | Tool calls | Tool p50 / p95 ms | LLM calls | Tokens in / out | Cost $ |",
            "|---|---|---|---|---|---|---|---|---|", *rows]


def _repeat_label(entry: Dict, manifest: Dict) -> str:
    return f" #{entry.get('repeat_index')}" if manifest.get("repeat", 1) > 1 and entry.get("repeat_index") else ""


def _run_status(entry: Dict, score: Optional[Dict]) -> str:
    return score["status"] if score else entry.get("status", "missing")


def score_batch(manifest: Dict, results: List[Tuple[Dict, Optional[Dict]]]) -> Dict:
    """pass^k per task: it passes only if every run of it passed and none is
    missing. Sorted and timestamp-free, so it is byte-stable."""
    tasks: Dict[str, Dict] = {}
    for entry, score in results:
        row = tasks.setdefault(entry.get("task_id"), {"runs": 0, "passed": 0, "failed_runs": []})
        row["runs"] += 1
        if _run_status(entry, score) == "pass":
            row["passed"] += 1
        else:
            row["failed_runs"].append(entry.get("run_id"))
    expected = manifest.get("expected") or {}
    for task_id in expected:
        tasks.setdefault(task_id, {"runs": 0, "passed": 0, "failed_runs": []})
    for task_id, row in tasks.items():
        row["expected"] = int(expected.get(task_id, row["runs"]))
        row["missing"] = max(0, row["expected"] - row["runs"])
        row["failed_runs"] = sorted(row["failed_runs"])
        row["pass_all"] = row["runs"] > 0 and row["missing"] == 0 and row["passed"] == row["runs"]
        n = max(row["runs"], row["expected"])  # a missing run counts as a failed one
        row["pass_at_k"] = {str(k): frac(pass_at_k(n, row["passed"], k)) for k in range(1, n + 1)}
        row["pass_hat_k"] = {str(k): frac(pass_hat_k(n, row["passed"], k)) for k in range(1, n + 1)}
    tasks = {k: tasks[k] for k in sorted(tasks)}
    n_tasks, n_all = len(tasks), sum(1 for r in tasks.values() if r["pass_all"])
    clusters = [[1] * r["passed"] + [0] * (max(r["runs"], r["expected"]) - r["passed"]) for r in tasks.values()]
    runs_total = sum(len(c) for c in clusters)
    lo, hi = wilson_interval(n_all, n_tasks)
    k_max = min((len(c) for c in clusters if c), default=0)
    mean_hat = {str(k): frac(sum((Fraction(r["pass_hat_k"][str(k)]) for r in tasks.values()), Fraction(0)) / n_tasks)
                for k in range(1, k_max + 1)}
    total = {"tasks": n_tasks, "tasks_passing_all": n_all,
             "tasks_passing_all_wilson95": [_4(lo), _4(hi)],
             "runs": runs_total,
             "run_pass_rate": frac(Fraction(sum(map(sum, clusters)), runs_total)) if runs_total else "0",
             "run_pass_rate_se_clustered": _4(clustered_se(clusters)),
             "pass_hat_k_mean": mean_hat}
    return {"scorer": SCORER_VERSION, "batch_id": manifest.get("batch_id"), "repeat": manifest.get("repeat", 1),
            "tasks": tasks, "total": total}


def _grade_entries(batch_dir: Path, *, write: bool) -> Tuple[Dict, List[Tuple[Dict, Optional[Dict]]]]:
    manifest = load_record(batch_dir / "manifest.json")
    runs_root = batch_dir.parent.parent  # runs/batches/<id> -> runs/
    results: List[Tuple[Dict, Optional[Dict]]] = []
    for entry in manifest.get("runs", []):
        run_dir = runs_root / entry["run_id"]
        if entry.get("status") != "ran":
            results.append((entry, None))
        elif not (run_dir / "taskrun.json").exists():
            results.append(({**entry, "status": "fail", "reason": "no taskrun.json was written"}, None))
        else:
            results.append((entry, grade_run(run_dir, write=write)))
    return manifest, results


def grade_batch(batch_dir: Path) -> Tuple[Path, List[Tuple[Dict, Optional[Dict]]]]:
    batch_dir = Path(batch_dir)
    manifest, results = _grade_entries(batch_dir, write=True)
    batch_score = score_batch(manifest, results)
    dump_record(batch_dir / BATCH_SCORE_FILE, batch_score)
    return render_batch_report(batch_dir, manifest, results, batch_score), results


def rescore_check(batch_dir: Path) -> Tuple[bool, List[str]]:
    """Re-grade in memory (no writes) and compare with what is saved:
    (identical?, one line per difference)."""
    batch_dir = Path(batch_dir)
    manifest, results = _grade_entries(batch_dir, write=False)
    runs_root = batch_dir.parent.parent
    diffs: List[str] = []
    for entry, score in results:
        if score is None:
            continue
        saved = runs_root / entry["run_id"] / "score.json"
        if not saved.exists():
            diffs.append(f"{entry['run_id']}: no saved score.json (batch never graded?)")
        elif _load_or_none(saved) != score:
            diffs.append(f"{entry['run_id']}: score.json differs from a fresh grade")
    saved_batch = batch_dir / BATCH_SCORE_FILE
    if not saved_batch.exists():
        diffs.append(f"{BATCH_SCORE_FILE}: missing (batch never graded?)")
    elif _load_or_none(saved_batch) != score_batch(manifest, results):
        diffs.append(f"{BATCH_SCORE_FILE}: differs from a fresh grade")
    return not diffs, diffs


def _load_or_none(path: Path) -> Optional[Dict]:
    try:
        return load_record(path)
    except ValueError:
        return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Grade saved harness runs (files only).")
    ap.add_argument("paths", nargs="+", type=Path, help="a batch dir, or run dirs")
    ap.add_argument("--check", action="store_true",
                    help="re-grade in memory and compare with the saved scores; write nothing")
    args = ap.parse_args(argv)
    if args.check:
        return _check_main(args.paths)
    failed = False
    for path in args.paths:
        if (path / "manifest.json").exists():
            report, results = grade_batch(path)
            for entry, score in results:
                status = score["status"] if score else entry.get("status", "missing")
                failed |= status == "fail"
                print(f"  {status:8} {entry.get('task_id')} [{entry.get('tenant')}]")
            total = load_record(path / BATCH_SCORE_FILE)["total"]
            print(f"  {total['tasks_passing_all']} of {total['tasks']} tasks pass on every run")
            print(f"[report: {report}]")
        elif (path / "taskrun.json").exists():
            score = grade_run(path)
            failed |= score["status"] == "fail"
            print(f"  {score['status']:8} {score['task_id']}  [{path / 'score.json'}]")
        else:
            print(f"  skipped  {path}: no manifest.json or taskrun.json")
    return 1 if failed else 0


def _check_main(paths: List[Path]) -> int:
    ok = True
    for path in paths:
        if not (path / "manifest.json").exists():
            print(f"  --check needs a batch dir (with manifest.json): {path}")
            ok = False
            continue
        same, diffs = rescore_check(path)
        ok = ok and same
        print(f"  {'identical' if same else 'DIFFERENT'}  {path}")
        for d in diffs:
            print(f"    - {d}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
