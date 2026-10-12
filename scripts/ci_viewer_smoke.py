"""
Viewer smoke check: serve a graded batch with the real viewer and request what a
person would open.

    python scripts/ci_viewer_smoke.py runs/batches/<batch_id> [--runs-dir runs]

Starts `python -m agentkit.viewer` as its own process on a free local port (127.0.0.1
only) -- exactly how a person runs it -- and checks:
  - the page and its static files load;
  - /api/batches lists the batch; /api/batches/<id> has every run, the report and the
    calibration result (when the batch was calibrated);
  - /api/runs/<id> for every run has the task record, score, graph and telemetry, and the
    telemetry tree has one "task" root (what the Timeline tab draws);
  - the viewer stays read-only (POST -> 405) and confined (path traversal -> 404).
Exit 1 on the first broken expectation list (all problems are printed).
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _get(base: str, path: str, method: str = "GET") -> Tuple[int, bytes]:
    req = urllib.request.Request(base + path, method=method, data=b"{}" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""


def _json(base: str, path: str, problems: List[str]) -> Any:
    status, body = _get(base, path)
    if status != 200:
        problems.append(f"GET {path} -> {status}")
        return None
    try:
        return json.loads(body)
    except ValueError:
        problems.append(f"GET {path} -> not JSON")
        return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(base: str, proc: subprocess.Popen, seconds: float = 20.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            if _get(base, "/api/batches")[0] == 200:
                return True
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            pass
        time.sleep(0.2)
    return False


def smoke(batch_dir: Path, runs_dir: Path) -> List[str]:
    from agentkit.viewer.server import STATIC_FILES

    problems: List[str] = []
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "agentkit.viewer", "--runs-dir", str(runs_dir), "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        if not _wait_until_up(base, proc):
            return [f"viewer did not start on {base} (exit code {proc.poll()})"]
        for path in ["/", *[f"/static/{name}" for name in sorted(STATIC_FILES) if name != "index.html"]]:
            status, body = _get(base, path)
            if status != 200 or not body:
                problems.append(f"GET {path} -> {status}")

        batch_id = batch_dir.name
        listed = _json(base, "/api/batches", problems) or []
        if batch_id not in {b.get("batch_id") for b in listed}:
            problems.append(f"/api/batches does not list {batch_id}")
        batch = _json(base, f"/api/batches/{urllib.parse.quote(batch_id)}", problems) or {}
        runs = batch.get("runs") or []
        if not runs:
            problems.append(f"batch {batch_id} shows no runs")
        if not batch.get("report"):
            problems.append(f"batch {batch_id} shows no report.md")
        if (batch_dir / "calibration.json").exists() and not batch.get("calibration"):
            problems.append(f"batch {batch_id} shows no calibration result")

        for row in runs:
            run_id = row.get("run_id")
            run = _json(base, f"/api/runs/{urllib.parse.quote(str(run_id))}", problems) or {}
            for key in ("taskrun", "score", "graph", "telemetry"):
                if not run.get(key):
                    problems.append(f"run {run_id}: no {key}")
            tree = (run.get("telemetry") or {}).get("tree") or []
            if run.get("telemetry") and (len(tree) != 1 or tree[0].get("kind") != "task"):
                problems.append(f"run {run_id}: telemetry tree has no single task root")

        status, _ = _get(base, "/api/batches", method="POST")
        if status != 405:
            problems.append(f"POST /api/batches -> {status}, expected 405 (read-only)")
        status, _ = _get(base, "/api/runs/..%2F..%2Fconfig")
        if status != 404:
            problems.append(f"path traversal -> {status}, expected 404")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Serve a batch with the viewer and check what it shows.")
    ap.add_argument("batch_dir", type=Path, help="runs/batches/<batch_id>")
    ap.add_argument("--runs-dir", type=Path, default=None, help="default: two levels above the batch dir")
    args = ap.parse_args(argv)
    runs_dir = args.runs_dir or args.batch_dir.resolve().parent.parent
    problems = smoke(args.batch_dir.resolve(), runs_dir)
    if problems:
        print(f"viewer smoke: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"viewer smoke: ok ({args.batch_dir.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
