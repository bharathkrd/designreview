# `capstone_evals.py` and `rescore.py` — run and re-grade the benchmark

*Reading order: **13th**. Thin wrappers over `agentkit/harness`.*

```bash
python capstone_evals.py [--skip-llm] [--only t01_battery_tray_rev_diff] [--sim packs/designreview/fixtures]   # run + grade
python rescore.py [runs/batches/<id> | runs/<run_id> ...]                                       # re-grade (files only)
```

- `capstone_evals.py` = `python -m agentkit.harness.batch --grade`: every task in `packs/designreview/tasks/`
  runs in its own subprocess, ground truth is captured before and after with the harness's own login, and the
  batch is graded into `score.json` files and `report.md`.
- `rescore.py` = `python -m agentkit.harness.grade` on the newest batch (or the paths given). No network, no
  LLM: fixing a check and re-grading never costs an agent run.
- Both pass through the batch flags `--batch-id <id>` and `--repeat N` (pass^k: a task passes only if every
  run passed; `report.md` ends its header with `**P of T tasks pass on every run.**`).
  `python -m agentkit.harness.grade --check runs/batches/<id>` proves a re-grade gives the same scores
  without writing anything.
- Since 2026-10-13 a batch can also be calibrated end to end:
  `python -m agentkit.harness.replay --calibrate runs/batches/<id> --sim packs/designreview/fixtures`
  re-runs each passing run from one node with a faulty result (offline) and proves the target check fails,
  while an unchanged control replay still passes. CI runs it after the mutants. See `agentkit_harness.md`.

## What replaced the first draft's axes

The first draft graded by searching the agent's prose for substrings (`"2.0" in answer`, "blocked" meaning
not ready). That passed "12.0 mm" as "2.0 mm", read "nothing is blocked" as not ready, and missed reworded
geometry claims. The verifiers in `packs/designreview/checks.py` compare the structured finding **and** the
answer with platform ground truth, handle negation per sentence, and report drift when the data moved during
the run. The first draft's flat `proofs/runs/*.json` files carry no ground truth and can't be graded by them.
