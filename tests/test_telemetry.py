"""
Offline tests for agentkit/telemetry (spans, run tree, metrics, export).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Use cases to cover:
  [ ] span(...) with no active tracer does nothing and records nothing
  [ ] Nested spans get the right parent_id; the root's trace_id is its own span_id
  [ ] dotted_order of a child starts with its parent's dotted_order + "."
  [ ] An exception inside a span marks it status "error" and is re-raised unchanged
  [ ] An unknown kind ("banana") raises ValueError
  [ ] bind_context(fn) bound in the submitting thread keeps the parent in pool threads
  [ ] 8 threads x 200 spans: no lost spans, all ids unique
  [ ] build_tree nests children under parents, orders them by start, keeps an orphan as a root
  [ ] percentile is nearest-rank: p50 of 10..100 is 50, p95 is 100, empty list gives None
  [ ] summarize counts errors (raised or ok=False) and totals LLM tokens and cache hits
  [ ] export_run then load_telemetry round-trips (format "agentkit-telemetry-v1")
  [ ] A handler's on_tool_end is called; a handler that raises does not break the run
  [ ] Offline batch: every run has telemetry.json with one "task" root; tool spans == journal lines
  [ ] Grading gives the same score.json with telemetry.json deleted
  [ ] A routed task has a "route" step span under the task span; the router's file-list read is a tool span
      under it
  [ ] Each "llm" span has the tier, the provider and the model of the call (never the prompt or a key)
Hint: Tracer("r1"), `with use_tracer(t): with span("task", "x"): ...`, then look at t.spans.
For the batch cases use the offline batch (see tests/README.md, "The whole harness offline").
"""

import pytest

from agentkit.telemetry import Tracer, bind_context, build_tree, percentile, span, summarize, use_tracer

# Write your tests below.
