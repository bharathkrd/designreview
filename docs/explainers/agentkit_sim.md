# `agentkit/sim/` — the platform, offline

*Reading order: **8th**. Files: `fixture.py`, `sim_platform.py`, `capture.py`.*

## 10,000-ft view

Record every MCP and REST exchange the tasks need, once, against the live platform; replay them offline
for both the agent and the harness, with injectable faults.

## Why it's written this way

- **Capture is generic and complete.** `capture_fixture()` runs every task (template answers, no LLM) and its
  ground-truth probes through `RecordingSeat` / `RecordingRest` wrappers. Nothing is hand-written, so the
  fixture holds exactly the calls an offline run makes.
- **Replay is exact and loud.** A call whose `(tool, canonical args)` wasn't captured raises
  "not in fixture — re-capture it" (`unclassified`), never an empty result that could make a test pass.
  Results are fresh copies every time.
- **Faults test behaviour under trouble.**
  - `drop_tool:<tool>` — absent from the catalogue; calling it refuses (`not_in_seat`)
  - `fail_once:<tool>:<kind>` / `fail_always:<tool>:<kind>` — e.g. `flaky`, `missing`
  - `edit_text:<old>=><new>` — after the agent finishes, rewrite every recorded result (MCP and REST):
    "another team edited the record during the run" → the grader must say `drift`
  Call faults fire only while `armed`; the harness arms them around the agent's run so its own ground-truth
  reads stay undisturbed.
- **Validated fixtures.** `SeatFixture` is a pydantic model (format, tenant, captured_at, tools, calls).
- **Fixtures carry the catalogue.** Since 2026-10-12 a capture stores the full tool definitions
  (`tool_defs`) and their `tools_fingerprint`; `SimPlatform.seat_catalog()` serves them. `python -m
  agentkit.harness.preflight --tenant <t>` (read-only) compares the live fingerprint with the fixture's and
  checks the pack's `required_tools`: a changed catalogue is a warning to re-capture, a missing or changed
  required tool is a problem (exit 1).
- **Replays run at capture time.** `SimSession` runs each task inside `agentkit.clock.frozen_now(<fixture
  captured_at>)`, so date-dependent answers (past-due milestones) match the day the fixture was captured, on
  any day. `AGENTKIT_FROZEN_NOW` overrides it.

## Fault-injection matrix (CI)

`scripts/ci_fault_matrix.py` runs the scenarios in `packs/designreview/ci_faults.toml`. Each one replays one
task with faults, grades it, and states the expected overall grade and, where it matters, the exact checks.
Every scenario must also finish the agent run (`ended = "done"`): a fault may lower the grade, never crash
the agent. Today's seven: an edit during the run gives `drift`; a flaky read is retried (`pass`); a removed
feedback tool degrades to a partial answer (`pass`); an unreadable release gate or schedule gives `fail` on
`release_gate_matches_db` / `schedule_matches_db`; a refusal survives a flaky or broken read (`pass`). The
script is domain-free; the scenarios are pack data.

## Per-tenant fixtures

A fixture holds one tenant's platform. `python -m agentkit.sim.capture --tenant <t>` runs only the tasks
whose `tenants` include `<t>` and writes `<pack>/fixtures/<t>.json`. `--sim` takes either one fixture
file (every task replays it) or the fixtures folder (each task replays `<its tenant>.json`); a missing
tenant fixture is an error that says how to capture it.

## Results on the captured fixtures

All nine tasks (six on Suryodaya, three on Keystone) pass offline in about a second. T01 under faults: `fail_once` flaky read → pass
(retried); `drop_tool:DesignFeedback.list` → pass (degrades without false claims); release readiness always
failing → fail (verdict unknown); rev C note edited during the run → drift.

## Data note

The fixtures (`packs/designreview/fixtures/suryodaya.json` ~430 KB, `keystone.json` ~115 KB) are snapshots of the course platform's
seed data, including person-like names in feedback text. Decide whether it belongs in git; offline tests skip
without them, and `python -m agentkit.sim.capture --tenant <tenant>` recreates them.

## How to test

`tests/test_sim_platform.py`.
