"""
Validate a results.json written by harness/runner.py against the Release 8.1 harness specification.

    python scripts/check_results_json.py runs/results-sim-suryodaya.json [--instance suryodaya]
           [--min-agent-tasks 8] [--expect all-pass | some-fail]

The specification:
  - top level: {"tasks": [...], "summary": "<text>"}
  - tasks: 1 to 200 entries; each has "id" (text, unique), "title" (text), "passed" (a strict boolean),
    "score" (a number from 0.0 to 1.0) and "evidence" (text)
Our own rules (from the admin's harness reviews):
  - with --instance, every id starts with "<instance>:"
  - a passed entry has score 1.0; a failed entry has evidence (a failure must say why)
  - with --min-agent-tasks N, at least N "<instance>:task:" entries (the real agent ran)
  - --expect all-pass: no entry failed; --expect some-fail: at least one failed (a planted fault was reported)

Exit 0 when the file is valid and the expectation holds; 1 otherwise, with each problem listed.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

MAX_TASKS = 200
FIELDS = ("id", "title", "passed", "score", "evidence")


def problems(data: Any, instance: Optional[str] = None, min_agent_tasks: int = 0,
             expect: Optional[str] = None) -> List[str]:
    out: List[str] = []
    if not isinstance(data, dict):
        return ["the top level is not an object"]
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        out.append('"summary" is missing or not text')
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return out + ['"tasks" is missing or not a list']
    if not 1 <= len(tasks) <= MAX_TASKS:
        out.append(f'"tasks" has {len(tasks)} entries (must be 1 to {MAX_TASKS})')
    seen = set()
    for i, t in enumerate(tasks):
        where = f"tasks[{i}]"
        if not isinstance(t, dict):
            out.append(f"{where} is not an object")
            continue
        missing = [f for f in FIELDS if f not in t]
        if missing:
            out.append(f"{where} has no {', '.join(missing)}")
            continue
        tid = t["id"]
        if not isinstance(tid, str) or not tid:
            out.append(f"{where}.id is not text")
        elif tid in seen:
            out.append(f"{where}.id {tid!r} is a duplicate")
        else:
            seen.add(tid)
            if instance and not tid.startswith(f"{instance}:"):
                out.append(f"{where}.id {tid!r} does not start with {instance + ':'!r}")
        if not isinstance(t["title"], str) or not t["title"]:
            out.append(f"{where}.title is not text")
        if not isinstance(t["passed"], bool):
            out.append(f"{where}.passed is {t['passed']!r}, not a strict boolean")
        score = t["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0:
            out.append(f"{where}.score is {score!r}, not a number from 0.0 to 1.0")
        elif t["passed"] is True and float(score) != 1.0:
            out.append(f"{where} passed but its score is {score}")
        if not isinstance(t["evidence"], str):
            out.append(f"{where}.evidence is not text")
        elif t["passed"] is False and not t["evidence"].strip():
            out.append(f"{where} failed without evidence")
    if min_agent_tasks and instance:
        n = sum(1 for t in tasks if isinstance(t, dict) and str(t.get("id", "")).startswith(f"{instance}:task:"))
        if n < min_agent_tasks:
            out.append(f"only {n} agent task entries (expected at least {min_agent_tasks}): did the agent run?")
    failed = [t.get("id") for t in tasks if isinstance(t, dict) and t.get("passed") is False]
    if expect == "all-pass" and failed:
        out.append(f"{len(failed)} entries failed, e.g. {failed[:3]}")
    if expect == "some-fail" and not failed:
        out.append("no entry failed, but a failure was expected (a planted fault was not reported)")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Validate a harness results.json.")
    ap.add_argument("path", type=Path)
    ap.add_argument("--instance", default=None)
    ap.add_argument("--min-agent-tasks", type=int, default=0)
    ap.add_argument("--expect", choices=["all-pass", "some-fail"], default=None)
    args = ap.parse_args(argv)
    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"{args.path}: cannot read: {e}")
        return 1
    found = problems(data, args.instance, args.min_agent_tasks, args.expect)
    n = len(data.get("tasks") or []) if isinstance(data, dict) else 0
    if found:
        print(f"{args.path}: {len(found)} problem(s) in {n} entries")
        for p in found[:50]:
            print(f"  - {p}")
        return 1
    print(f"{args.path}: valid ({n} entries; {data.get('summary')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
