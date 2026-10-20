# `agentkit/telemetry/` — the run tree: timings, tokens, retries

*Reading order: **9th** (after the harness). Files: `spans.py`, `runtree.py`, `metrics.py`, `exporter.py`.
Added 2026-10-12 (integration Phase 5). Written in ASD-STE100 (Simplified Technical English) style,
2026-10-14.*

## Overview

```
run_one.run_task ── span task ──┬── span step "route" (only for a routed task)
                                ├── span node (engine, one per graph node; runs in the thread pool)
                                │      └── span tool (JournaledSeatClient: one per journaled MCP call)
                                │             attrs: ok, rows, http_status, response_bytes; events: re-login, retry
                                ├── span step "planner" (after each node finishes)
                                ├── span step "build_finding"
                                └── span step "narrate" ── span llm (LLMGateway.call_detailed)
                                                               attrs: tier, provider, model, tokens, stop_reason, cached
                         ──► runs/<run_id>/telemetry.json  (spans + tree + summary; never graded)
                         ──► report.md "## Performance" (per run: ms, nodes, tool calls, p50/p95, LLM tokens, cost, models)
                         ──► viewer "Timeline" tab
```

## Design decisions

- **Plain Python, no SDK.** The project uses no tracing SDK and no collector. The dependency guard rejects
  them. The design comes from an external open-source run-tree method. This module is a new, small
  implementation of that method.
- **The span record.** Each span has:
  - `span_id`, `parent_id` and `trace_id` (the id of the root);
  - `dotted_order`: segments of `<start time><id>`, joined by `.` from the root. A sort on this field sorts
    the tree;
  - `run_type` (`chain`, `tool`, `llm` or `retriever`) and `events`.

  A child never starts before its parent.
- **Propagation.** A `ContextVar` keeps the current span. `span()` and `traced` open children of it. Work for
  another thread runs in a copy of the context of the thread that submitted it.
- **Bookkeeping.** A map goes from each id to its span. A span with an unknown parent becomes a root.
  `Tracer(handlers=[...])` calls `on_<run_type>_start`, `_end` and `_error(span)`. If a handler raises an
  exception, the tracer ignores it. The exception goes up only when the handler sets `raise_error = True`.
- **Off means off.** When no tracer is active, `span()` gives an object that does nothing. Thus each
  instrumented line runs as before. Only `run_one` starts tracing, one time for each run.
- **Threads.** The graph engine runs nodes in a `ThreadPoolExecutor`. Python does not copy the context into
  pool threads. Thus the engine submits `bind_context(fn)`, which it binds in the submitting thread. Then the
  node spans are under the task span, and the tool spans are under their node.
- **Never graded.** Timings are different on each run. The grader never reads `telemetry.json`.
  `batch_score.json` has no timing, so `grade --check` stays byte-stable. Only `report.md` has the
  Performance section.
- **No secrets and no prompt text.** Spans have names, ids, counts, statuses and token numbers. They never
  have the prompt, the answer, the tool arguments or a key. The tool journal still has clipped arguments.
- **Limits.** The gateway does not stream, so there is no time to the first token. The wire-level retries in
  `UrllibWire` are not separate spans. The retries of the engine and of the gateway are events.

## Key types

| Name | Use |
|---|---|
| `Tracer(run_id, handlers=)` | The tracer of one run. |
| `Span` | `span_id`, `parent_id`, `trace_id`, `dotted_order`, `kind`, `run_type`, `name`, `start_time`, `start_ms`, `end_ms`, `duration_ms`, `status`, `error`, `attrs`, `events`. |
| `span(kind, name, **attrs)`, `traced(kind)` | Open a child of the current span. |
| `use_tracer(tracer)`, `bind_context(fn)` | Start tracing; carry the context into a thread. |
| `annotate(**attrs)`, `add_event(name)` | Add data to the current span. |
| `build_tree(spans)`, `summarize(spans)`, `percentile(values, p)` | Make the tree and the summary. `percentile` uses the nearest rank. |
| `export_run(tracer, run_dir)`, `load_telemetry(run_dir)` | Write and read `telemetry.json`. |

The kinds are `task`, `node`, `tool`, `llm`, `step` and `retriever`.

## Before and after

| | Before 2026-10-12 | After |
|---|---|---|
| Timing of one run | Node `started_at` and `finished_at` in `graph.json`; `seconds` on each journal line; LLM latency in `llm_ledger.json` | All of these, **and** one tree that connects them. The tree also shows the queue wait, the wire status and size, the retries and the logins. |
| Batch view | A status table for each run | Also a Performance table in `report.md` |
| Viewer | An Evidence tab (graph nodes only) | Also a Timeline tab (task, node, tool, llm, step) |

## Send the spans to a collector (OTLP, since 2026-10-20)

`otlp.py` converts `telemetry.json` to the OTLP/HTTP JSON format and sends it to an OpenTelemetry collector.
It uses no OpenTelemetry SDK: a guard test keeps the SDK out of `agentkit`. Thus the same spans can go to
Jaeger, Grafana Tempo, CloudWatch or a hosted trace tool.

```
python -m agentkit.telemetry.otlp runs/<run_id> [runs/batches/<batch_id>] --endpoint http://127.0.0.1:4318
python -m agentkit.telemetry.otlp runs/batches/<batch_id> --print      # write the payload, send nothing
```

Set `OTEL_EXPORTER_OTLP_ENDPOINT`, and each run sends its spans when it writes `telemetry.json`.
`OTEL_EXPORTER_OTLP_HEADERS` (`k1=v1,k2=v2`) gives the headers, for example an API key.

| Our span | OTLP |
|---|---|
| One run | One `resourceSpans` with `service.name` and `agentkit.run_id` |
| `run_id` | `traceId`: 32 hex characters of SHA-256 of the run id. The same run always has the same trace id. |
| `span_id`, `parent_id` | `spanId`, `parentSpanId`: 16 hex characters of SHA-256 of the run id and the span id |
| `start_time`, `duration_ms` | `startTimeUnixNano`, `endTimeUnixNano` |
| `status`, `error` | `status.code` 1 (ok) or 2 (error) with the message |
| `attrs`, `events` | Attributes and events, plus `agentkit.kind` |
| `llm` span | Also `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` |
| `tool` span | Also `tool.name` |

A failed export never fails a run. The run record gets the warning "OTLP export failed". An offline run
(`AGENTKIT_OFFLINE=1`) sends only to a collector on this computer (127.0.0.1, `localhost`). CI sends the CI
batch to a stub collector with `scripts/ci_otlp_smoke.py` and checks that every span arrived.

## How to test

1. The reference tests are `tests_local/test_telemetry.py` and `tests_local/test_otlp_export.py`. The
   hand-written template is `tests/test_telemetry.py`.
2. For an offline run, run `python -m agentkit.harness.batch --sim packs/designreview/fixtures --skip-llm --grade`.
3. Run `python -m agentkit.viewer` and open the Timeline tab of a run.
