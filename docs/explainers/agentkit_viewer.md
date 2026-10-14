# `agentkit/viewer/` — the read-only run viewer

*Reading order: **10th**. The viewer has no domain words. It shows the files that the harness wrote, for each
pack. Written in ASD-STE100 (Simplified Technical English) style, 2026-10-14.*

## Overview

```bash
python -m agentkit.viewer                    # http://127.0.0.1:8765/
python -m agentkit.viewer --runs-dir /tmp/runs --port 9000
```

The viewer is a small local web page on the run folders (`runs/<run_id>/` and `runs/batches/<batch_id>/`).
All the data that it shows is already on disk. The viewer only makes the evidence easy to read. This helps
when you explain a graded run, or when you look for the cause of a failed check.

| Page | Contents |
|---|---|
| **Batches** | Each batch, newest first: runs, status counts, LLM on or off, calibration result. |
| **All runs** | Each run folder, also the runs from outside a batch (`capstone_agent.py --task`). |
| **Batch** | A table of task and tenant, with the status and the failed checks of each run; the calibration of each mutant; `report.md`. |
| **Run → Answer** | The answer, its source (llm or template), the claim-audit result, each attempt, the warnings. |
| **Run → Finding** | The finding as a tree that you can expand and collapse. The tree is generic, so it shows the finding of each pack. |
| **Run → Checks** | Each check, with its status and detail. |
| **Run → Evidence** | The graph as a timeline: node, action, verdict, dependencies, the source of the node (plan or planner), tries, a time bar, reason. |
| **Run → Timeline** | The run tree from `telemetry.json` (task, node, tool, llm, step), with bars on the clock of the run, and p50 and p95 for each kind. |
| **Run → Tool calls** | The tool journal. Writes have a highlight. |
| **Run → Ground truth** | Each observation before and after the run. The viewer marks the observations that changed (drift) and shows the difference. |
| **Run → Cost** | The LLM calls: provider, model, tokens, cost, latency, stop reason, and if the provider gave the usage or the gateway estimated it. |

## Design decisions

- **The server writes bodies in parts of 64 KB (since 2026-10-12).** One large `wfile.write()` sometimes cut
  responses at about 64 KB on the Windows loopback. This occurred on 1 to 4 % of run pages of 130 KB, and
  then the browser stopped. The CI smoke check found the problem. A standard `http.server`, which copies in
  parts, did not show it. CI now gets each run of the CI batch through the real viewer
  (`scripts/ci_viewer_smoke.py`).
- **The Timeline tab (since 2026-10-12).** It shows `telemetry.json`. A run from before telemetry shows a note
  in place of the tree. The run API includes `telemetry` in its file list.
- **No framework, no build step, no new dependency.** The server is `http.server` from the standard library.
  The page is one HTML file, one script and one stylesheet. Thus it is easy to audit the rule "no agent
  frameworks", and there is nothing to install.
- **Read-only by design.** The server accepts only GET and HEAD. Each other method gets 405. No code in the
  module writes a file. The viewer intentionally cannot start runs or file hand-offs.
- **You can test the logic without a socket.** `ViewerApp.handle(path)` gives `(status, content type, body)`.
  `make_server()` is a thin wrapper.
- **No domain words.** The viewer reads the file formats of the harness: task, taskrun, score, graph,
  journal, ground truth, ledger, manifest, calibration. It shows the finding as a generic tree.

## Safety

Run data has platform text from other teams. Thus the viewer treats it as hostile.

| Risk | Guard |
|---|---|
| Path traversal (`../`, `%2F`, `\`, symlinks) | Each id must agree with `^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$`, must not have `..`, and must resolve to a direct child of the runs folder (or the batches folder). |
| Access to other files | The static files come from a fixed list: `index.html`, `app.js`, `style.css`. |
| Text that becomes markup (XSS) | The page makes each element with `textContent`, never with `innerHTML`. Links go only to `#/` routes. JSON responses also escape `<`, `>` and `&` as `\u` sequences. |
| Injected scripts | `Content-Security-Policy: default-src 'self'; script-src 'self'; ...`. No inline script and no third-party files. `X-Content-Type-Options: nosniff`. |
| Other computers read run data | The server binds to `127.0.0.1` by default. Each other `--host` value shows a warning. |

## API

| Route | Result |
|---|---|
| `GET /api/batches` | `[{batch_id, started_at, finished_at, skip_llm, write, runs, status_counts, calibration_ok}]` |
| `GET /api/runs` | `[{run_id, task_id, tenant, ended, started_at, score_status}]` |
| `GET /api/batches/<id>` | `{manifest, runs: [entry + score_status, counts, failing], report, calibration}` |
| `GET /api/runs/<id>` | `{task, taskrun, score, graph, journal, before, after, ground_truth_changes, ledger, telemetry, stdout}` |

A missing file is `null`. A file that the viewer cannot parse is `{"_unreadable": "<name>"}`. Thus the viewer
shows a half-written run or a crashed run. It does not fail on it.

## How to test

1. The hand-written template is `tests/test_viewer.py`. It is offline. Its docstring has the list of tests
   to write.
2. Make a runs folder in `tmp_path`, by hand or with an offline sim batch.
3. Call `ViewerApp(runs_dir).handle(path)`.
4. For the HTTP layer, run `make_server(runs_dir, port=0)` in a thread.
