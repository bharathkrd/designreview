# `agentkit/record/` — the run record

*Reading order: **6th**. Files: `run_record.py`, `durable_io.py`. `core/harness.py` re-exports the same classes.*

## 10,000-ft view

Every run produces one `TaskRun`, written to disk **before any work starts** and again at the end, with
every write crash-safe.

## Why it's written this way

- **Saved first, as running.** `open_in(run_dir)` writes `taskrun.json` with `ended = "running"`. A crash
  therefore leaves evidence, and the grader fails it ("record still says running: the run crashed").
- **Atomic writes.** Write to a temp file, `fsync`, then `os.replace`; the swap is retried briefly because on
  Windows antivirus/OneDrive can hold the target for a moment. A reader never sees half a file.
- **Append-only logs** (`JsonlAppender`) are flushed per line and thread-safe; `read_jsonl` tolerates a torn
  last line left by a crash.
- **Old API kept.** `TaskRun(task_id, prompt)`, `add_step(kind, target, ok, detail)`, `save(proofs_dir)`
  (flat `<task_id>_<started_at>.json`) and `TaskRun.load()` work as before; `load()` ignores fields it
  doesn't know, so older code can read newer records.
- **`paused` (since 2026-10-13).** Before: a run ended `done` or `error`. A run started with
  `--require-approval` that stops before a write now ends `paused`, with the paused nodes as steps whose
  `status` is `paused` and no answer yet. The grader fails it (`run_completed`) until `run_one --resume`
  finishes the same folder.

## Key fields

`TaskRun`: `task_id, prompt, steps, claimed_answer, ended (running|done|error|paused), error, seconds,
started_at, run_id, tenant, dry_run, harness_task, pack, finding, answer_source, warnings`.
`Step`: `kind, target, ok, detail, status (the node verdict), reason, error_kind, attempts, added_by, seconds`.

## How to test

`tests/test_harness.py` — use `tmp_path` as the run folder.
