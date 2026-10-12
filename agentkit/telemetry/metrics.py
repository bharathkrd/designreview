"""
Latency and token figures from a list of span dicts.

- `percentile(values, p)`: nearest-rank (the smallest value with at least p%
  of the data at or below it); None for no data. Nearest-rank never invents a
  latency that wasn't measured, which interpolation can.
- `summarize(spans)`: per kind -> count, p50_ms, p95_ms, max_ms, total_ms,
  errors (a span that raised, or a tool/LLM span marked ok=False); plus LLM
  calls, provider-reported input/output tokens and cache hits.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence


def percentile(values: Sequence[float], p: float) -> Optional[float]:
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    rank = max(1, math.ceil(p / 100.0 * len(data)))
    return data[min(rank, len(data)) - 1]


def _is_error(span: Dict[str, Any]) -> bool:
    return span.get("status") == "error" or (span.get("attrs") or {}).get("ok") is False


def latency_stats(spans: List[Dict[str, Any]]) -> Dict[str, Any]:
    durations = [s["duration_ms"] for s in spans if s.get("duration_ms") is not None]
    return {"count": len(spans), "p50_ms": percentile(durations, 50), "p95_ms": percentile(durations, 95),
            "max_ms": max(durations) if durations else None, "total_ms": round(sum(durations), 3),
            "errors": sum(1 for s in spans if _is_error(s))}


def summarize(spans: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    spans = list(spans)
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for s in spans:
        by_kind.setdefault(s["kind"], []).append(s)
    llm = by_kind.get("llm", [])

    def total(key: str) -> int:
        return sum(int((s.get("attrs") or {}).get(key) or 0) for s in llm)

    return {"by_kind": {k: latency_stats(v) for k, v in sorted(by_kind.items())},
            "llm": {"calls": len(llm), "input_tokens": total("input_tokens"), "output_tokens": total("output_tokens"),
                    "cached": sum(1 for s in llm if (s.get("attrs") or {}).get("cached"))}}
