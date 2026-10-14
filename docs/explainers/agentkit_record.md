# `agentkit/record/` — the run record

*Reading order: **6th**. Files: `run_record.py`, `durable_io.py`. `core/harness.py` gives the same classes.
Written in ASD-STE100 (Simplified Technical English) style, 2026-10-14.*

## Overview

Each run makes one `TaskRun`. The run writes it to disk **before any work starts**, and again at the end. Each
write is safe from a crash.

## Design decisions

- **Save first, as "running".** `open_in(run_dir)` writes `taskrun.json` with `ended = "running"`. Thus a
  crash leaves evidence. The grader fails such a run: "record still says running: the run crashed".
- **Atomic writes.** The code writes to a temporary file, calls `fsync`, and then calls `os.replace`. On
  Windows, antivirus software or OneDrive can lock the target for a short time. Thus the code tries the
  replace again for a short time. A reader never sees half a file.
- **Append-only logs.** `JsonlAppender` writes each line to disk immediately. It is thread-safe. A crash can
  leave a broken last line. `read_jsonl` ignores that line.
- **The old API stays.** These work as before:
  - `TaskRun(task_id, prompt)`;
  - `add_step(kind, target, ok, detail)`;
  - `save(proofs_dir)`, which writes a flat `<task_id>_<started_at>.json` file;
  - `TaskRun.load()`. It ignores fields that it does not know. Thus old code can read new records.
- **The `paused` state (since 2026-10-13).** Before, a run ended as `done` or `error`. Now a run with
  `--require-approval` that stops before a write ends as `paused`. The paused nodes are steps with
  `status = paused`, and the run has no answer yet. The grader fails the run (`run_completed`). Then
  `run_one --resume` completes the run in the same folder.

## Key fields

| Type | Fields |
|---|---|
| `TaskRun` | `task_id`, `prompt`, `steps`, `claimed_answer`, `ended` (`running`, `done`, `error` or `paused`), `error`, `seconds`, `started_at`, `run_id`, `tenant`, `dry_run`, `harness_task`, `pack`, `finding`, `answer_source`, `warnings`, `route` |
| `Step` | `kind`, `target`, `ok`, `detail`, `status` (the node verdict), `reason`, `error_kind`, `attempts`, `added_by`, `seconds` |

## How to test

The hand-written template is `tests/test_harness.py`. Use `tmp_path` as the run folder.
