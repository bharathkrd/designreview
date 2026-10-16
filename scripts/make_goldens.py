"""
Print candidate [[golden]] blocks for a design-review task, from one of its saved runs -- for a PERSON to check.

    python scripts/make_goldens.py runs/<run_id>                 # one run folder
    python scripts/make_goldens.py --batch runs/batches/<id> t01_battery_tray_rev_diff

A golden is only worth something when a person has checked it against the platform (the seed data, or
ENTITY_SCHEMAS.md / the platform UI). Values copied from the agent unchecked only show that the agent agrees
with itself. So every block is printed with `note = "CHECK: ..."`: replace it with where you checked the value,
delete the blocks you could not check, and paste the rest at the end of the task's TOML file. Then run the
offline batch and `python -m agentkit.harness.mutants` (agentkit/harness/goldens.py has the format).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]


def _toml(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def candidates(taskrun: Dict[str, Any], tools: List[str]) -> List[Tuple[str, str, Any, Optional[str]]]:
    """(path, comparison, value, field) for the facts a design-review answer stands on."""
    f = taskrun.get("finding") or {}
    out: List[Tuple[str, str, Any, Optional[str]]] = [("finding.outcome", "equals", f.get("outcome"), None)]
    rd = f.get("revision_delta") or {}
    for key in ("from_version", "to_version"):
        if rd.get(key) is not None:
            out.append((f"finding.revision_delta.{key}", "equals", rd[key], None))
    compared = {rd.get("from_version"), rd.get("to_version")}
    for v in rd.get("versions") or []:
        if v.get("version_number") in compared and v.get("rev"):
            texts = [q.get("text") for q in v.get("quantities") or []]
            out.append((f"finding.revision_delta.versions[rev={v['rev']}].quantities", "values", texts, "text"))
    if rd.get("change_notes"):
        out.append(("finding.revision_delta.change_notes", "values", rd["change_notes"], None))
    gate = f.get("release_gate") or {}
    for key in ("ready", "critical_open"):
        if gate.get(key) is not None:
            out.append((f"finding.release_gate.{key}", "equals", gate[key], None))
    h = f.get("handoffs")
    if isinstance(h, dict):
        out.append(("finding.handoffs.proposed", "values", [p.get("owner") for p in h.get("proposed") or []], "owner"))
        out.append(("finding.handoffs.filed", "equals", bool(h.get("filed")), None))
    s = f.get("schedule")
    if isinstance(s, dict) and s.get("past_due") is not None:
        out.append(("finding.schedule.past_due", "values", s["past_due"], None))
    route = taskrun.get("route") or {}
    if route.get("plan"):
        out.append(("route.plan", "equals", route["plan"], None))
        if (route.get("params") or {}).get("file_id"):
            out.append(("route.params.file_id", "equals", route["params"]["file_id"], None))
    if tools is not None:
        out.append(("tools", "only", sorted(set(tools)), None) if tools else ("tools", "length", 0, None))
    return [c for c in out if c[2] is not None]


def render(rows: List[Tuple[str, str, Any, Optional[str]]], source: str) -> str:
    lines = [f"# Candidate goldens from {source}. CHECK every value against the platform before you keep it."]
    for path, kind, value, field in rows:
        lines += ["", "[[golden]]", f"path = {_toml(path)}"]
        if field:
            lines.append(f"field = {_toml(field)}")
        lines += [f"{kind} = {_toml(value)}", 'note = "CHECK: where did you confirm this value?"']
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Print candidate goldens for a person to check.")
    ap.add_argument("run_or_task", help="a run folder, or with --batch a task id")
    ap.add_argument("--batch", type=Path, help="a graded batch folder; the task's first run is used")
    args = ap.parse_args(argv)
    run_dir = Path(args.run_or_task)
    if args.batch:
        manifest = json.loads((args.batch / "manifest.json").read_text(encoding="utf-8"))
        entry = next((e for e in manifest.get("runs") or [] if e.get("task_id") == args.run_or_task), None)
        if entry is None:
            print(f"no run of {args.run_or_task!r} in {args.batch}", file=sys.stderr)
            return 2
        run_dir = args.batch.parent.parent / entry["run_id"]
    try:
        taskrun = json.loads((run_dir / "taskrun.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"cannot read {run_dir / 'taskrun.json'}: {e}", file=sys.stderr)
        return 2
    journal = run_dir / "tool_journal.jsonl"
    tools = [json.loads(l).get("tool") for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if journal.exists() else None
    print(render(candidates(taskrun, [t for t in tools or [] if t] if tools is not None else None), run_dir.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
