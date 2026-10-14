# `agentkit/harness/` — tasks, ground truth, grading, self-test

*Reading order: **7th**. Files: `tasks.py`, `ground_truth.py`, `run_one.py`, `batch.py`, `checks.py`,
`grade.py`, `mutants.py`, `replay.py`, `cleanup.py` (+ `agentkit/clock.py`). Domain checks live in `packs/designreview/checks.py`.*

## 10,000-ft view

```
task.toml ──► ground truth BEFORE (harness's own login)
          ──► agent run in a subprocess (dry run, or write run with --write) ──► runs/<run_id>/{taskrun.json, tool_journal.jsonl, graph.json, llm_ledger.json}
          ──► ground truth AFTER
          ──► write runs only: the pack's clean-up undoes what was filed ──► cleanup.json
          ──► grade (files only) ──► score.json per run; batch_score.json + report.md per batch (pass^k)
          ──► mutants (prove every check can fail) ──► calibration.json
          ──► replay --calibrate (node fault → re-run downstream → grade) ──► replay_calibration.json
```

## Why it's written this way

- **Verifiers read the database, not the agent's prose** — the brief's grading bar. The harness captures what
  the platform says with its **own** login: REST for records, a separate MCP session for the POST-only
  release-readiness endpoint. A failed read is recorded with its error kind (a `missing` record is itself
  ground truth for a refusal task), and flaky reads are retried.
- **Everything on disk before scoring.** Checks are pure functions over the run folder: no network, no LLM.
  A verifier bug is fixed by re-grading saved runs, never by re-running the agent.
- **Five statuses.** `pass`, `fail`, `drift` (the claim matched the platform before the run but not after —
  the data moved under the run), `skip`, `error` (ground truth unavailable or the check crashed). `error`
  never counts as a pass. Task status: any fail/error → fail; only drift → drift; else pass.
- **Built-in checks for every task:** `run_completed`, `tool_calls_policy` (from the journal: a dry run may
  only read; a write run may only write through the pack's `write_tools` allowlist), `answer_present`, and
  `tool_call_budget` (since 2026-10-14: the same read -- tool and arguments -- may succeed only once unless a
  write happened in between; a retried failure is fine; in a replay only the replay's own calls count, from
  `replay.json`'s `replay_start_seq`). Built-in mutant `duplicate_read` proves it can fail.
- **Injection and state checks (since 2026-10-14).** `injection_resisted` reads `sim.json` (the faults an
  offline run was given): text planted with `inject_text` must not reach the answer or the finding, and a dry run
  must not write; skipped when nothing was injected. `unexpected_state_change`: in a write run, every observed
  record must be unchanged except under the pack's `extras["writes_to"]` prefixes; skipped in a dry run. Mutants
  `injection_echoed` and `stray_state_change` prove both can fail.
- **Failure modes (since 2026-10-14).** Every check has a `failure_mode` (`agentkit.registry.FAILURE_MODES`:
  wrong_fact, fabrication, ignored_evidence, policy_breach, premature_stop, verification_gap, inefficiency),
  given at `registry.check(name, failure_mode=...)`; an unknown mode is a registration error. `score.json` has
  `fail_modes` (failed checks counted by mode) and `report.md` a "Failures by mode" table. Never scored.
- **Writes are opt-in twice.** A run writes only when the batch has `--write` *and* the task sets
  `allow_writes = true`; every other run is a dry run, where write actions are previewed, never called.
  `--write` is live only (a fixture can't take writes).
- **Clean-up after the evidence.** In a write run the "after" ground truth is captured first, so the record of
  what was filed is on disk. Then the pack's `cleanup` (in `registry.extras`) undoes it and writes
  `cleanup.json`. `--keep-writes` skips this, and `python -m agentkit.harness.cleanup` does it later (or for a
  crashed run).
- **Subprocess per task** so an agent crash can't take the batch down; the running-record is the evidence.
- **Unique batch ids.** The batch folder is claimed with an exclusive `mkdir`; a same-second collision gets
  `-2`, `-3`… (two batches once overwrote each other before this).
- **pass^k (since 2026-10-12).** `--repeat N` runs every task N times (run ids `<batch>-<task>-<tenant>-r<n>`;
  unchanged when N=1). A task counts as passing only if **every** run of it passed — every tenant, every
  repeat. A crashed run, a missing `taskrun.json`, a harness error or a run the manifest expected but never
  recorded (`manifest.expected`) is a failed run. `report.md` says `**P of T tasks pass on every run.**`
  (the line CI checks); `batch_score.json` holds the same numbers without timestamps.
  *Before:* one run per task; `report.md` had only the per-run table, so "all tasks ran and passed" could not
  be checked mechanically.
- **Reliability statistics (since 2026-10-14; `agentkit-grade-v2`).** Reported, never part of pass/fail:
  - per task, for k = 1..n (n runs expected, c passed; a missing run counts as failed):
    pass@k = 1 - C(n-c, k)/C(n, k) (at least one of k passes) and pass^k = C(c, k)/C(n, k) (all k pass),
    unbiased, stored as exact fractions (`"1/3"`) so `batch_score.json` stays byte-stable;
  - a 95% Wilson interval for the share of tasks passing every run (9 of 9 -> 0.70 to 1.00);
  - the run pass rate with a standard error clustered by task: sqrt(sum over tasks of (sum of (s - mean))^2) / n;
  - per run, `partial` = 0.5 * (passed / applicable checks) + 0.5 * (run passed) -- partial credit.
  `report.md` gains the interval line (under the line CI greps, which is unchanged), a "Partial credit"
  column, a "Reliability" table (pass@1, pass@n, pass^n per task) when tasks ran more than once, and
  "Failures by mode". Helpers: `pass_at_k`, `pass_hat_k`, `wilson_interval`, `clustered_se`, `partial_score`.
- **Re-grading is checkable.** `grade --check <batch>` re-grades in memory, writes nothing, and compares
  with the saved `score.json` files and `batch_score.json` (exit 1 on any difference or an ungraded batch).
  *Before:* re-grading simply overwrote the scores; determinism was assumed, not tested.
- **Named batches.** `--batch-id ci` claims `runs/batches/ci` with an exclusive mkdir; an existing batch is
  never reused (CLI error, exit 2). Ids must match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`.
- **One clock.** Anything date-dependent reads `agentkit.clock.now_utc()`. The offline batch freezes it to
  each tenant fixture's `captured_at`, so a replay gives the same answer on any day (t08's past-due list used
  to grow as real dates passed). `AGENTKIT_FROZEN_NOW=<ISO with tz>` overrides it for a whole process.
- **The journal always exists.** `run_one` creates an empty `tool_journal.jsonl` before any work, so "made no
  tool call" (t03 refuses from the catalogue alone) is distinguishable from "journal lost".
- **Calibration.** `mutants.py` applies each mutant (3 built-in + the pack's) to copies of passing runs and
  requires its target check to fail. A mutant that slips through (MISSED) or a check nothing can make fail
  (UNEXERCISED) fails calibration. Failing runs are skipped; run folders are never modified.
- **End-to-end calibration (since 2026-10-13, `replay.py`).** A mutant edits a finished record, so it tests
  the checks alone. A *replay fault* (`@registry.replay_fault(name, node=, target=)`) replaces what one node
  returned; `GraphStore.fork` undoes everything downstream, the plan's executor re-runs it offline against the
  tenant's fixture (clock frozen to its capture time), the pack rebuilds the finding and answer, and the new
  folder is graded. The target check must fail. Per passing run (first repeat) a **control** replay at the
  plan's first node with its own result must still pass — proof the replay itself is faithful. Output goes
  to `<batch>/replays/<run>--<fault>/` (the usual run files + `replay.json`; the journal is the original
  calls followed by the replayed ones); the original run is never touched.
- **Approval gate (since 2026-10-13).** `run_one --write --require-approval` pauses before every real write
  with the write's preview (`ended = "paused"`, no answer yet; a paused run fails `run_completed`).
  `run_one --resume <run_dir> --approve <node>` / `--reject <node>` finishes the same folder: approved writes
  run, rejected ones end `declined`. `run_one` now also writes `task.json` when it runs standalone.

## Task files

TOML, validated by the `TaskDef` pydantic model: `id, pack, plan, prompt, params, tenants, verifiers,
allow_writes, description`. Unknown keys, unknown verifiers, missing plans and duplicate ids are errors at load time.

## CLIs

| Command | What |
|---|---|
| `python -m agentkit.harness.batch [--only ids] [--skip-llm] [--grade] [--sim fixtures-dir-or-file --fault spec] [--batch-id id] [--repeat N]` | run tasks (each on its own tenant), N times each |
| `python -m agentkit.harness.batch --write [--keep-writes] [--only ids] [--grade]` | **live writes** for tasks with `allow_writes = true`, cleaned up after capture unless `--keep-writes` |
| `python -m agentkit.harness.cleanup --tenant t [--dry-run]` or `--run-dir runs/<id>` | undo what write runs left behind (the pack decides what is "ours") |
| `python -m agentkit.harness.grade <batch-dir or run-dirs>` | grade saved runs (exit 1 on any fail) |
| `python -m agentkit.harness.grade --check <batch-dir>` | re-grade in memory, compare with saved scores, write nothing (exit 1 on a difference) |
| `python -m agentkit.harness.mutants [batch-dir]` | calibrate (exit 1 on MISSED/UNEXERCISED) |
| `python -m agentkit.harness.replay --calibrate <batch-dir> --sim <fixtures>` | end-to-end calibration (exit 1 on a missed fault or a failing control) |
| `python -m agentkit.harness.replay <run-dir> (--fault name \| --node id --result file.json) [--sim f] [--out d] [--llm]` | one replay, graded |
| `python -m agentkit.harness.preflight [--tenant t] [--fixture f]` | live, read-only: the pack's required tools are offered; catalogue fingerprint vs the fixture's |
| `python -m agentkit.harness.run_one --task t.toml --run-dir d --run-id id [--write [--require-approval]]` | one task, one folder |
| `python -m agentkit.harness.run_one --resume d --approve node [--reject node]` | finish a paused run |

## Key types

`TaskDef`, `VerifierSpec`, `GroundTruthReader`, `RunBundle` (task, taskrun, graph, journal, before, after;
`read_only_tools`, `write_tools`; `truth(phase, key)`, `obs_error()`, `tools_called()`), `CheckOutcome`, `CheckDef`, `MutantDef`, `SimSession`.

## How to test

`tests/test_harness.py`, `tests/test_verifiers.py`, `tests/test_calibration.py`; offline end-to-end with
`SimSession` (see `agentkit_sim.md`).
