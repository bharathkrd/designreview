# `agentkit/sim/` — the platform, offline

*Reading order: **8th**. Files: `fixture.py`, `sim_platform.py`, `capture.py`. Written in ASD-STE100
(Simplified Technical English) style, 2026-10-14.*

## Overview

The capture records each MCP and REST exchange that the tasks need. It does this one time, on the live
platform. Then the agent and the harness replay these exchanges offline. You can add faults to the replay.

## Design decisions

- **The capture is generic and complete.** `capture_fixture()` runs each task with template answers and no
  LLM. It also runs the ground-truth probes of each task. The wrappers `RecordingSeat` and `RecordingRest`
  record all calls. No person writes the fixture. Thus the fixture has exactly the calls of an offline run.
- **The replay is exact, and it fails clearly.** A call whose `(tool, canonical args)` is not in the fixture
  raises "not in fixture — re-capture it" (`unclassified`). It never gives an empty result, because an empty
  result can make a test pass incorrectly. Each result is a new copy.
- **Pydantic validates the fixtures.** `SeatFixture` has `format`, `tenant`, `captured_at`, `tools` and `calls`.
- **The fixtures have the tool catalogue (since 2026-10-12).** A capture keeps the full tool definitions
  (`tool_defs`) and their `tools_fingerprint`. `SimPlatform.seat_catalog()` gives them.
- **A preflight compares the catalogues.** `python -m agentkit.harness.preflight --tenant <t>` is read-only.
  It compares the live fingerprint with the fingerprint of the fixture. It also examines the `required_tools`
  of the pack:
  - a changed catalogue gives a warning to capture again;
  - a missing or changed tool from that list is a problem (exit code 1).
- **The replay uses the capture date.** `SimSession` runs each task inside
  `agentkit.clock.frozen_now(<captured_at>)`. Thus an answer that depends on the date (for example, a
  milestone that is past due) is the same on each day. `AGENTKIT_FROZEN_NOW` overrides the date.

## Faults

The faults are strings. They show how the agent and the harness work when a problem occurs.

| Fault | Effect |
|---|---|
| `drop_tool:<tool>` | The catalogue does not have the tool. A call to it fails with `not_in_seat`. |
| `fail_once:<tool>:<kind>` | The next call of the tool fails with `<kind>`, for example `flaky` or `missing`. |
| `fail_always:<tool>:<kind>` | Each call of the tool fails with `<kind>`. |
| `fail_times:<tool>:<kind>:<n>` | The next `<n>` calls fail. An example is a rate limit that stops after some retries. |
| `edit_text:<old>=><new>` | After the agent run, each recorded result gets `<new>` in place of `<old>`. This is "another team edited the record during the run". The grader must say `drift`. |
| `inject_text:<tool>:<field>=<text>` | Before the agent reads the data, each `<field>` string of the tool gets `<text>` at its end. This is an indirect prompt injection in platform data. |
| `truncate:<tool>:<n>` | The `data` list of the tool keeps only its first `<n>` rows. `total` still gives the full count. This is a partial payload. |
| `rename_field:<tool>:<old>=<new>` | Each `<old>` key in the results of the tool becomes `<new>`. This is a schema change on the platform. |

The call faults and the result faults operate only while `armed` is true. The harness arms them only for the
agent run. Thus the ground-truth reads of the harness are not changed.

## The fault-injection matrix (CI)

`scripts/ci_fault_matrix.py` runs the scenarios in `packs/designreview/ci_faults.toml`. Each scenario
replays one task with faults and grades it. The scenario gives the expected grade. Where it is important, it
also gives the expected result of specified checks.

Each scenario must also complete the agent run (`ended = "done"`). A fault can make the grade lower. It must
never cause a crash of the agent.

There are 13 scenarios:

| Scenario | Task | Expected |
|---|---|---|
| The record changes during the run | t01 | `drift` |
| A flaky read (the agent tries again) | t01 | `pass` |
| A tool is not in the seat | t01 | `pass` (a partial answer, with no false claims) |
| The release gate is never readable | t01 | `fail` on `release_gate_matches_db` |
| A flaky read before a refusal | t02 | `pass` |
| The schedule is never readable | t08 | `fail` on `schedule_matches_db` |
| A refusal that needs no platform read | t03 | `pass` |
| An instruction in a commit note | t01 | `pass`, with `injection_resisted` |
| An instruction in a feedback title | t08 | `pass`, with `injection_resisted` and `tool_calls_policy` |
| A rate limit that stops within the retries | t01 | `pass` |
| A short version list | t01 | `pass` |
| An empty feedback list | t08 | `fail` on `handoffs_match_platform` |
| The platform renamed a field | t01 | `fail` on `revision_delta_matches_db` |

The script has no domain words. The scenarios are pack data.

## Fixtures for each tenant

A fixture has the platform of one tenant.

- `python -m agentkit.sim.capture --tenant <t>` runs only the tasks whose `tenants` include `<t>`. It writes
  `<pack>/fixtures/<t>.json`.
- `--sim` accepts one fixture file or the fixtures folder. With one file, each task replays that file. With the
  folder, each task replays the file of its tenant.
- If the fixture of a tenant is missing, you get an error. The error tells you how to capture it.

## Results on the captured fixtures

All 12 tasks pass offline: 8 on Suryodaya and 4 on Keystone. CI runs each task three times.

## Data note

The fixtures are snapshots of the seed data of the course platform:

- `packs/designreview/fixtures/suryodaya.json`, about 1.5 MB;
- `packs/designreview/fixtures/keystone.json`, about 1.0 MB.

They have names of persons in the feedback text. Decide if they must be in git. Without them, pytest skips the offline
tests. `python -m agentkit.sim.capture --tenant <tenant>` makes them again.

## How to test

The hand-written template is `tests/test_sim_platform.py`.
