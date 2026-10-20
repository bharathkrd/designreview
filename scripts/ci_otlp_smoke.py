"""
CI smoke check for the OTLP export: send a batch's spans to a stub collector and check that every
span arrived.

    python scripts/ci_otlp_smoke.py runs/batches/ci

Offline: the collector is a small HTTP server on 127.0.0.1 started by this script (an offline run
may send to loopback). Exit 0 when the collector received one resourceSpans per run with every span
of each telemetry.json; 1 otherwise.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkit.record.durable_io import load_record  # noqa: E402
from agentkit.telemetry.otlp import main as otlp_main, run_dirs  # noqa: E402


def collector():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            received.append((self.path, json.loads(body)))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


def main(argv=None) -> int:
    batch = Path((argv or sys.argv[1:] or ["runs/batches/ci"])[0])
    runs = run_dirs(batch)
    if not runs:
        print(f"no runs with telemetry.json in {batch}")
        return 1
    expected = {load_record(d / "telemetry.json")["run_id"]: len(load_record(d / "telemetry.json")["spans"])
                for d in runs}
    server, received = collector()
    try:
        rc = otlp_main([str(batch), "--endpoint", f"http://127.0.0.1:{server.server_address[1]}"])
    finally:
        server.shutdown()
    if rc != 0 or len(received) != 1 or received[0][0] != "/v1/traces":
        print(f"FAIL: exit {rc}, {len(received)} request(s)")
        return 1
    got = {}
    for rs in received[0][1]["resourceSpans"]:
        run_id = next(a["value"]["stringValue"] for a in rs["resource"]["attributes"] if a["key"] == "agentkit.run_id")
        got[run_id] = sum(len(ss["spans"]) for ss in rs["scopeSpans"])
    if got != expected:
        missing = {k: (expected.get(k), got.get(k)) for k in set(expected) | set(got) if expected.get(k) != got.get(k)}
        print(f"FAIL: span counts differ (expected, received): {missing}")
        return 1
    print(f"OTLP smoke OK: {len(got)} run(s), {sum(got.values())} spans received")
    return 0


if __name__ == "__main__":
    sys.exit(main())
