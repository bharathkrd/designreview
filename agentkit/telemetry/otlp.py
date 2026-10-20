"""
Send a run's spans to any OpenTelemetry collector, without an OpenTelemetry SDK.

    python -m agentkit.telemetry.otlp runs/<run_id> [runs/batches/<batch_id> ...]
           [--endpoint http://127.0.0.1:4318] [--print]

telemetry.json (exporter.py) is converted to the OTLP/HTTP JSON encoding and POSTed to
<endpoint>/v1/traces. The endpoint and headers come from the standard variables
OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_EXPORTER_OTLP_HEADERS ("k1=v1,k2=v2"), so the same spans
reach Jaeger, Grafana Tempo, CloudWatch or a hosted trace tool. --print writes the payload
instead of sending it.

The mapping:
  one run         -> one resourceSpans (service.name, agentkit.run_id)
  traceId         -> 32 hex of sha256(run_id): the same run always has the same trace id
  spanId          -> 16 hex of sha256(run_id + span_id); parentSpanId the same way
  times           -> Unix nanoseconds: the span's wall-clock start + its measured duration
  status          -> ok = 1, error = 2 (with the error text)
  attributes      -> every span attribute (agentkit.kind, agentkit.run_type and the span's own),
                     plus the GenAI conventions on llm spans (gen_ai.system, gen_ai.request.model,
                     gen_ai.usage.input_tokens, gen_ai.usage.output_tokens) and tool.name on tool spans

Export is evidence only, like telemetry.json: a failed export never changes a run or a grade.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote, urlsplit

import httpx

from agentkit.record.durable_io import load_record
from agentkit.telemetry.exporter import TELEMETRY_FILE
from agentkit.transport.wire import refuse_if_offline

ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
HEADERS_ENV = "OTEL_EXPORTER_OTLP_HEADERS"
SERVICE_NAME = "agentkit"
SCOPE = {"name": "agentkit.telemetry", "version": "1"}
SPAN_KIND = {"task": 1, "node": 1, "step": 1, "tool": 3, "llm": 3, "retriever": 3}  # INTERNAL=1, CLIENT=3
STATUS = {"ok": 1, "error": 2}
TIMEOUT_S = 10.0
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def _hex(text: str, length: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _ns(iso: str) -> int:
    t = dt.datetime.fromisoformat(iso)
    return int(t.timestamp()) * 1_000_000_000 + t.microsecond * 1_000


def _value(v: Any) -> Dict[str, Any]:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}  # 64-bit integers are strings in the JSON encoding
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_value(x) for x in v]}}
    return {"stringValue": json.dumps(v, default=str, sort_keys=True)}


def _attributes(attrs: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"key": k, "value": _value(v)} for k, v in attrs.items() if v is not None]


def _span_attrs(s: Dict[str, Any]) -> Dict[str, Any]:
    a = s.get("attrs") or {}
    out = {"agentkit.kind": s.get("kind"), "agentkit.run_type": s.get("run_type"), **a}
    if s.get("kind") == "llm":
        out.update({"gen_ai.operation.name": "chat", "gen_ai.system": a.get("provider"),
                    "gen_ai.request.model": a.get("model"), "gen_ai.usage.input_tokens": a.get("input_tokens"),
                    "gen_ai.usage.output_tokens": a.get("output_tokens")})
    elif s.get("kind") == "tool":
        out["tool.name"] = s.get("name")
    return out


def _span(run_id: str, s: Dict[str, Any]) -> Dict[str, Any]:
    start = _ns(s["start_time"])
    end = start + int(round((s.get("duration_ms") or 0.0) * 1_000_000))
    out: Dict[str, Any] = {
        "traceId": _hex(run_id, 32), "spanId": _hex(run_id + s["span_id"], 16), "name": s.get("name") or "",
        "kind": SPAN_KIND.get(s.get("kind"), 1), "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
        "attributes": _attributes(_span_attrs(s)),
        "events": [{"name": e.get("name", ""), "timeUnixNano": str(_ns(e["time"]) if e.get("time") else start),
                    "attributes": _attributes({k: v for k, v in e.items() if k not in ("name", "time")})}
                   for e in s.get("events") or []],
        "status": {"code": STATUS.get(s.get("status"), 0), **({"message": s["error"]} if s.get("error") else {})},
    }
    if s.get("parent_id"):
        out["parentSpanId"] = _hex(run_id + s["parent_id"], 16)
    return out


def to_otlp(telemetry: Dict[str, Any], service_name: str = SERVICE_NAME) -> Dict[str, Any]:
    """One telemetry.json -> one OTLP/HTTP JSON request body."""
    run_id = telemetry.get("run_id") or ""
    resource = {"attributes": _attributes({"service.name": service_name, "agentkit.run_id": run_id,
                                           "agentkit.format": telemetry.get("format")})}
    spans = [_span(run_id, s) for s in telemetry.get("spans") or [] if s.get("start_time")]
    return {"resourceSpans": [{"resource": resource, "scopeSpans": [{"scope": SCOPE, "spans": spans}]}]}


def merge(payloads: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {"resourceSpans": [rs for p in payloads for rs in p["resourceSpans"]]}


def parse_headers(raw: Optional[str]) -> Dict[str, str]:
    """OTEL_EXPORTER_OTLP_HEADERS: "k1=v1,k2=v2", values URL-encoded."""
    out = {}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[unquote(k.strip())] = unquote(v.strip())
    return out


def traces_url(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    return endpoint if endpoint.endswith("/v1/traces") else endpoint + "/v1/traces"


def post(payload: Dict[str, Any], endpoint: str, headers: Optional[Dict[str, str]] = None, *,
         transport: Optional[httpx.BaseTransport] = None) -> int:
    """POST one payload; returns the HTTP status. Raises on a network error or a non-2xx status.
    An offline run (AGENTKIT_OFFLINE=1) may still send to a collector on this computer (loopback)."""
    if transport is None and urlsplit(endpoint).hostname not in LOOPBACK:
        refuse_if_offline("OTLP export")
    with httpx.Client(transport=transport, timeout=TIMEOUT_S) as client:
        resp = client.post(traces_url(endpoint), json=payload,
                           headers={"Content-Type": "application/json", **(headers or {})})
    resp.raise_for_status()
    return resp.status_code


def run_dirs(path: Path) -> List[Path]:
    """A run folder, or every run of a batch folder (runs/batches/<id>, its manifest names the runs)."""
    path = Path(path)
    if (path / TELEMETRY_FILE).exists():
        return [path]
    manifest = path / "manifest.json"
    if manifest.exists():
        runs_root = path.parent.parent  # runs/batches/<id> -> runs/
        return [runs_root / r["run_id"] for r in load_record(manifest).get("runs") or []
                if (runs_root / r["run_id"] / TELEMETRY_FILE).exists()]
    return []


def payload_for(paths: Iterable[Path], service_name: str = SERVICE_NAME) -> Dict[str, Any]:
    return merge(to_otlp(load_record(d / TELEMETRY_FILE), service_name) for p in paths for d in run_dirs(p))


def export_from_env(run_dir: Path, *, transport: Optional[httpx.BaseTransport] = None) -> Optional[int]:
    """What run_one calls after writing telemetry.json: send it when OTEL_EXPORTER_OTLP_ENDPOINT is
    set (None when it is not). The caller turns any exception into a run warning."""
    endpoint = os.environ.get(ENDPOINT_ENV)
    if not endpoint:
        return None
    return post(payload_for([run_dir]), endpoint, parse_headers(os.environ.get(HEADERS_ENV)), transport=transport)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Send run spans to an OpenTelemetry collector (OTLP/HTTP JSON).")
    ap.add_argument("paths", nargs="+", type=Path, help="run folders or batch folders")
    ap.add_argument("--endpoint", default=os.environ.get(ENDPOINT_ENV), help=f"default: ${ENDPOINT_ENV}")
    ap.add_argument("--service-name", default=SERVICE_NAME)
    ap.add_argument("--print", action="store_true", help="print the OTLP JSON instead of sending it")
    args = ap.parse_args(argv)
    payload = payload_for(args.paths, args.service_name)
    runs, spans = len(payload["resourceSpans"]), sum(len(rs["scopeSpans"][0]["spans"]) for rs in payload["resourceSpans"])
    if not runs:
        print("no telemetry.json found in the given paths", file=sys.stderr)
        return 1
    if args.print:
        print(json.dumps(payload, indent=1))
        return 0
    if not args.endpoint:
        print(f"no endpoint: pass --endpoint or set {ENDPOINT_ENV} (or use --print)", file=sys.stderr)
        return 2
    status = post(payload, args.endpoint, parse_headers(os.environ.get(HEADERS_ENV)))
    print(f"sent {spans} spans of {runs} run(s) to {traces_url(args.endpoint)}: HTTP {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
