"""
Write and read runs/<run_id>/telemetry.json.

    {"format": "agentkit-telemetry-v1", "run_id": ..., "spans": [...flat...],
     "tree": [...build_tree...], "summary": {...summarize...}}

Telemetry is evidence about *how* a run went (timings, tokens, retries); it is
never graded, so a missing or partial file can't change a score.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from agentkit.record.durable_io import dump_record, load_record
from agentkit.telemetry.metrics import summarize
from agentkit.telemetry.runtree import build_tree
from agentkit.telemetry.spans import Tracer

TELEMETRY_FILE = "telemetry.json"
TELEMETRY_FORMAT = "agentkit-telemetry-v1"


def snapshot(tracer: Tracer) -> Dict[str, Any]:
    spans = tracer.to_dicts()
    return {"format": TELEMETRY_FORMAT, "run_id": tracer.run_id, "spans": spans,
            "tree": build_tree(spans), "summary": summarize(spans)}


def export_run(tracer: Tracer, run_dir: Path) -> Path:
    return dump_record(Path(run_dir) / TELEMETRY_FILE, snapshot(tracer))


def load_telemetry(run_dir: Path) -> Optional[Dict[str, Any]]:
    path = Path(run_dir)
    path = path / TELEMETRY_FILE if path.is_dir() else path
    return load_record(path) if path.exists() else None
