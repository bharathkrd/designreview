"""
agentkit.telemetry -- a plain-Python run tree for every agent run.

Spans (task -> node -> tool / llm / step) with timings, attributes and events,
collected per run and written to runs/<run_id>/telemetry.json. Nothing here
grades anything, and with no active tracer every instrumentation point is a
no-op. No tracing SDK or collector is used: spans.py explains the algorithm
(an external open-source run-tree design, rebuilt in plain Python).
"""

from agentkit.telemetry.exporter import TELEMETRY_FILE, export_run, load_telemetry
from agentkit.telemetry.metrics import percentile, summarize
from agentkit.telemetry.runtree import build_tree
from agentkit.telemetry.spans import (KINDS, NULL_SPAN, Span, Tracer, add_event, annotate, bind_context,
                                      current_span, current_tracer, span, traced, use_tracer)

__all__ = ["KINDS", "NULL_SPAN", "Span", "TELEMETRY_FILE", "Tracer", "add_event", "annotate", "bind_context",
           "build_tree", "current_span", "current_tracer", "export_run", "load_telemetry", "percentile", "span",
           "summarize", "traced", "use_tracer"]
