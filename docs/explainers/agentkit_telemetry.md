# `agentkit/telemetry/` — the run tree: timings, tokens, retries

*Reading order: **9th** (after the harness). Files: `spans.py`, `runtree.py`, `metrics.py`, `exporter.py`.
Added 2026-10-12 (integration Phase 5).*

## 10,000-ft view

```
run_one.run_task ── span task ──┬── span node (engine, one per graph node; runs in the thread pool)
                                │      └── span tool (JournaledSeatClient: one per journaled MCP call)
                                │             attrs: ok, rows, http_status, response_bytes; events: re-login, retry
                                ├── span step "planner" (after each node finishes)
                                ├── span step "build_finding"
                                └── span step "narrate" ── span llm (LLMGateway.call_detailed)
                                                               attrs: provider, model, tokens, stop_reason, cached
                         ──► runs/<run_id>/telemetry.json  (spans + tree + summary; never graded)
                         ──► report.md "## Performance" (per run: ms, nodes, tool calls, p50/p95, LLM tokens, cost)
                         ──► viewer "Timeline" tab
```

## Why it's written this way

- **Plain Python, no SDK.** No tracing SDK or collector; the dependency guard rejects them. The design is
  adapted from an external open-source run-tree approach (referred to from outside sources), rebuilt here:
  - **The record:** `span_id`, `parent_id`, `trace_id` (the root's id), `dotted_order`
    (`<%Y%m%dT%H%M%S%fZ start><id>` segments joined by `.` from the root, so sorting by it sorts the tree),
    `run_type` (`chain / tool / llm / retriever`), `events`; a child never starts before its parent.
  - **Propagation:** a `ContextVar` holds the current span; `span()` / `traced` open children of it, and work
    for another thread runs in a copy of the submitter's context.
  - **Bookkeeping:** an id → span map; a span whose parent is unknown becomes a root. A
    `Tracer(handlers=[...])` calls `on_<run_type>_start / _end / _error(span)`; a handler that raises is
    ignored unless it sets `raise_error = True`.
- **Off means off.** With no active tracer, `span()` yields a do-nothing object: every instrumented line runs
  exactly as before. Only `run_one` turns tracing on, per run.
- **Threads.** The graph engine runs nodes in a `ThreadPoolExecutor`, and Python doesn't copy context into
  pool threads. The engine submits `bind_context(fn)` (bound in the submitting thread), so node spans nest
  under the task span and tool spans under their node.
- **Never graded.** Timings vary run to run. Grading never reads `telemetry.json`, `batch_score.json` holds no
  timing, and `grade --check` stays byte-stable; the Performance section lives only in `report.md`.
- **No secrets, no prompt text.** Spans carry names, ids, counts, statuses and token numbers — never the prompt,
  the answer, tool arguments or a key. (The tool journal still holds clipped arguments, as before.)
- **Honest limits.** The gateway is non-streaming, so there is no time-to-first-token. Wire-level retries inside
  `UrllibWire` are not separate spans; the engine's per-action retries and the gateway's retries are events.

## Key types

`Tracer(run_id, handlers=)` · `Span` (`span_id, parent_id, trace_id, dotted_order, kind, run_type, name,
start_time, start_ms, end_ms, duration_ms, status, error, attrs, events`) · `span(kind, name, **attrs)` ·
`traced(kind)` · `use_tracer(tracer)` · `bind_context(fn)` · `annotate(**attrs)` / `add_event(name)` on the
current span · `build_tree(spans)` · `percentile(values, p)` (nearest rank) · `summarize(spans)` ·
`export_run(tracer, run_dir)` / `load_telemetry(run_dir)`.

Kinds: `task, node, tool, llm, step, retriever`.

## Before → after

| | Before 2026-10-12 | After |
|---|---|---|
| Per-run timing | node `started_at`/`finished_at` in `graph.json`; `seconds` per journal line; LLM latency in `llm_ledger.json` | all of that **plus** one tree linking them, with queue wait, wire status/bytes, retries and re-logins |
| Batch view | per-run status table | + Performance table in `report.md` |
| Viewer | Evidence tab (graph nodes only) | + Timeline tab (task → node → tool / llm / step) |

## How to test

`tests_local/test_telemetry.py` (reference); the hand-written to-do list is `tests/test_telemetry.py`.
Offline end to end: `python -m agentkit.harness.batch --sim packs/designreview/fixtures --skip-llm --grade`,
then open a run's Timeline tab in `python -m agentkit.viewer`.
