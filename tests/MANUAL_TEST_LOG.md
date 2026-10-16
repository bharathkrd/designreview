# Manual Test Log — Team 21 (Design Review)

Checks done by hand in the browser (UI counts, sorting, thumbnails, crashes, date pickers).
Record every run, including passes. A failure that is a real platform bug becomes a bug report: put the returned ID in **Bug ID**.

- Suryodaya: https://agentswitch.theschoolofai.in/v/DesignReview:Home
- Keystone: https://class.agentswitch.theschoolofai.in/v/DesignReview:Home
- Views: see [`links.md`](../links.md) and [`research.md`](../research.md) §2

## How to fill in a row
| Field | Meaning |
| :-- | :-- |
| ID | `M-<area>-<nn>`, e.g. `M-REV-01` |
| Tester / Date | Who ran it, and when |
| Tenant | Suryodaya / Keystone / both |
| Record(s) | Page, file / review / feedback number or ID |
| Steps | Numbered, exact clicks and values |
| Expected | What should happen |
| Actual | What did happen (copy error text, attach a screenshot filename) |
| Result | PASS / FAIL / BLOCKED |
| Bug ID | Bug report ID if filed, or "known: <id>" for a duplicate |

## Areas to cover
- [ ] **CNT**: dashboard cards match their list pages (projects, files, reviews, feedback, shares)
- [ ] **SORT**: priority / due-date ordering on dashboard and lists
- [ ] **REV**: version history visible for the Battery Tray / Propeller, and matching the API
- [ ] **REVIEW**: review create / edit validation (due date, required fields), transitions in the UI
- [ ] **FB**: Feedback panel on files with unusual tags; feedback transitions in the UI
- [ ] **VIEW**: 3D viewer, thumbnails, glTF/STL previews
- [ ] **REL**: release readiness page vs the API result for the same file
- [ ] **SHARE**: create / revoke / expire share links
- [ ] **PERM**: things team21 must NOT be able to do (release / approve, other apps)

## Log

| ID | Tester | Date | Tenant | Record(s) | Steps | Expected | Actual | Result | Bug ID |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| M-NAV-01 | Claude (AI-assisted, browser) | 2026-10-13 | both | sidebar | 1. Open DesignReview:Home. 2. Read the FEEDBACK group. 3. Open `/open_issues` | Same views as `research.md` §2 | FEEDBACK has one item, "Findings" (`/findings`, "Workspace Feedback" with saved views + filters); `/open_issues` lands on `/findings` | PASS (UI changed, no agent impact) | — |
| M-REL-01 | Claude (AI-assisted, browser) | 2026-10-13 | Suryodaya | DF-2026-00001 Battery Tray (`39b69109…`) | 1. Release readiness. 2. Search "BEV-BT-2400". 3. Read the panel | Matches `release_readiness` API / fixture | Release blocked; candidate version 3; no assembly tree, open critical findings, no review bound; 1 blocking finding "2.0 mm inside bend radius on 2.0 mm HR — cracking risk" | PASS | — |
| M-REL-02 | Claude (AI-assisted, browser) | 2026-10-13 | Suryodaya | DF-2026-00012 Propeller (`1131649b…`) | as M-REL-01, search "AP-PR-001" | Matches API / fixture | Blocked; version 2; no assembly tree, no review bound; no blockers | PASS | — |
| M-REL-03 | Claude (AI-assisted, browser) | 2026-10-13 | Suryodaya | DF-2026-00008 Bench Vice (`4e6bf256…`) | as M-REL-01, search "ST-VICE-150 Bench" | Matches API / fixture | Blocked; version 3; not in ready state, no completed conversion, no review bound | PASS | — |
| M-REL-04 | Claude (AI-assisted, browser) | 2026-10-13 | Keystone | DF-2026-00026 Hydraulic Manifold Mount — Machined Part (`5f3c30f5…`) | as M-REL-01, search "Hydraulic Manifold Mount", pick "Machined Part" | Matches API / fixture | Blocked; version 6; not in ready state, no assembly tree, no review bound | PASS | — |
| M-REL-05 | Claude (AI-assisted, browser) | 2026-10-13 | Keystone | DF-2026-00001 Auger Drive — Housing Cover (`d3156003…`) | as M-REL-01, search "Housing Cover" | Matches API / fixture | Blocked; version 3; no assembly tree, no review bound | PASS | — |
| M-REL-06 | Claude (AI-assisted, browser) | 2026-10-13 | Suryodaya | `release_readiness?release_file=39b69109…` | 1. Open the deep link directly | The Battery Tray's readiness | The picker shows only 25 of 100 files; the URL is rewritten to `release_file=0bc2b05d…` and the page shows "Part model — Maintenance" ("No stored version is available for release") | FAIL (candidate bug, not filed) | |
| M-FB-01 | Claude (AI-assisted, browser + read-only API) | 2026-10-13 | Suryodaya | FB-2026-00001, FB-2026-00002, FB-2026-00103 | 1. Findings page. 2. Read the rows. 3. Look each up by file | Battery Tray findings as in the fixture | FB-00001 critical / in progress on the tray; FB-00002 high / in progress on the **Base Pan flat pattern DF-2026-00002**, not the tray; FB-00103 "T21-TEST 20261009-133721" open / low on the Propeller | PASS | — |
| M-CNT-01 | Claude (AI-assisted, browser) | 2026-10-13 | both | Dashboard cards | 1. Open the dashboard. 2. Read the cards right after load and after 5 s | Cards show the counts | Suryodaya 101 / 21 / 22 / 4. Keystone first shows 0 and "No … yet" everywhere, then 5 / 3 / 12 / 5. Card-vs-list counts not compared yet | PASS (partial) | — |

### Tests to author for these rows (hand-written, in `tests/`)

> **To author:** each row above has a matching AI reference test in tests_local/test_ui_snapshot_2026_10_13.py
> (git-ignored, not for submission). Write your own version in `tests/` by hand, per the course rule, and tick
> the box when it exists. Suggested file: `tests/test_ui_snapshot.py` (no marker for the offline ones, `live` for
> the platform ones).

- [ ] **M-NAV-01** — no automated test (UI-only). *To author:* optional; a live test that GETs /findings and /open_issues is not possible with the API seat; keep as manual.
- [ ] **M-REL-01…05** — *To author:*
      - offline test: for each task file, the fixture's release_readiness result has ready=False, the UI's version_number, the UI's reasons in order, and the UI's blocker titles (table in research.md §2.0). Reference: test_fixture_release_readiness_matches_the_ui.
      - offline test: run each task (t01, t04, t05, t06, t07) on the sim with frozen_now(captured_at) and assert finding["release_gate"] equals the same UI values. Reference: test_agent_release_gate_states_what_the_ui_shows.
      - live test (marker live): the same values from the live endpoint.designreview.release_readiness. Reference: test_live_release_readiness_still_matches_the_ui_snapshot.
- [ ] **M-REL-06** — *To author:* none needed in our suite (platform UI bug); if it is filed, put the bug ID in the row.
- [ ] **M-FB-01** — *To author:* offline test: FB-2026-00001 is in the Battery Tray feedback in the fixture with (title, critical, in_progress); FB-2026-00002 is NOT, and the 4.2 mm is in the rev C commit note; FB-2026-00103 is in the Propeller feedback. References: test_fixture_battery_tray_findings_match_the_ui, test_base_pan_finding_is_not_part_of_the_battery_tray_evidence, test_fixture_has_the_team_test_feedback_seen_on_the_findings_page. Live version: test_live_battery_tray_findings_still_match.
- [ ] **M-CNT-01** — *To author:* live test comparing each dashboard card with its list total (DesignProject, DesignReview open, DesignFeedback open, DesignShare active) once the card definitions are confirmed; not written yet.
- [ ] **API unchanged** (research.md §2.0) — *To author:* offline test: both fixtures record 323 tools and fingerprint fbadee4421f15020; live test: SeatRpcClient.catalog().fingerprint() is the same. References: test_fixture_catalogue_is_the_one_live_today, test_live_catalogue_unchanged.


## Automated live runs (tests_local, AI reference suite)

Full runs of the git-ignored reference suite against the live platform and real LLM providers. The full output
and per-test results stay local (`tests_local/live_run_<date>.log` / `.xml`, credentials masked).

| ID | Tester / Date | Commit | Command | Environment | Result | Failures and cause |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| A-LIVE-01 | Claude (AI-assisted) / 2026-10-14 | `e94acb5` (main) | `pytest tests_local -m "(live or agent or gateway_live) and not writes"` | `.env` as is | **FAIL**: 14 passed, 7 failed, 30 errors | 30 errors: Suryodaya login 401 -- `.env` holds the server-run `AGENTSWITCH_TOKEN`/`BASE_URL`/`INSTANCE`; `agentkit/config.py:tenant_login()` checks for the token *before* loading `.env`, so the first login uses the password and later Suryodaya logins send an empty one (the test fixture always logs in with a password). 7 failures: `OPENAI_API_KEY` in `.env` puts `openai` first in every tier (`gateway.candidate_order`), so each single-provider test was answered by OpenAI |
| A-LIVE-02 | Claude (AI-assisted) / 2026-10-14 | `e94acb5` (main) | same | `.env` with the six server-run variables blanked for the process | **PASS except providers**: 48 passed, 3 failed, 3 xfailed (3 min 44 s); log: `tests_local/live_run_2026-10-14.log` | all live platform tests (both tenants) and all agent runs pass. Provider accounts: Gemini HTTP 402 (prepaid credits depleted), Cerebras HTTP 402 (payment required), NVIDIA HTTP 410 (`.env` `NVIDIA_MODEL` = `meta/llama-3.3-70b-instruct`, retired 2026-08-26; `routing.toml` already uses `mistralai/mistral-large-2-instruct`) |
| A-LIVE-03 | Claude (AI-assisted) / 2026-10-14 | `5149c70` + the token-mode fix (branch `feat/research-gaps-remaining`) | same | `.env` **as is** (nothing blanked) | **PASS except providers**: 48 passed, 3 failed, 3 xfailed (2 min 47 s) | the A-LIVE-01 failures are gone: `tenant_login()` now uses token mode only for variables the runner injects into the process (not copies in `.env`), and the gateway puts `openai` first only for an injected key. Remaining: the same 3 provider accounts as A-LIVE-02 |
| A-LIVE-04 | Claude (AI-assisted) / 2026-10-14 | `b67bd38` (draft PR #14, batches 3-6) | same | `.env` **as is** | **PASS except providers**: 48 passed, 3 failed, 3 xfailed (2 min 55 s); log: `tests_local/live_run_2026-10-14_b67bd38.log` | all live platform tests (both tenants) and all live agent runs pass on the batch 3-6 code (quarantine, retrieval gate, cascade, router). Remaining: the same 3 provider accounts (Gemini 402, Cerebras 402, NVIDIA 410) |

Not run: the 18 `writes` tests (they create and change `T21-TEST` records on the shared platform).

- [ ] **A-LIVE-01** -- *To author:* offline test: with `AGENTSWITCH_TOKEN`/`AGENTSWITCH_BASE_URL` only in a temporary `.env`, two calls of `tenant_login("suryodaya")` return the same thing (today the first returns the password and the second an empty one). Mark it `xfail` until `tenant_login` is fixed.
- [ ] **A-LIVE-02** -- *To author:* offline test: `LLMGateway(..., env={"OPENAI_API_KEY": "x"})`: `candidate_order("default")` starts with `openai` (documents the server-run behaviour); without the key it equals `routing.toml`'s order.

### Live LLM batches (harness, all 12 tasks, dry run)

`python -m agentkit.harness.batch --batch-id <id> --grade` against the live platform with LLM narration on
(read-only: every run is a dry run). The "Models" column comes from each run's `llm_ledger.json`; the batch
folders (`runs/batches/<id>/report.md`) stay local.

| ID | Tester / Date | Commit | Batch id | Environment | Result | Models that wrote the answers | Cost (USD) | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| A-LIVE-05 | Claude (AI-assisted) / 2026-10-14 | `b67bd38` + DeepSeek/Moonshot/LM Studio rows (before `651e4f5`) | `live-llm-deepseek-2026-10-14` | `.env` as is | **PASS, but wrong provider**: 12 of 12 | openai:gpt-4o-mini (12) | 0.026 | DeepSeek was first in each tier, but each answer came from OpenAI: each task's child process took the `.env` copy of `OPENAI_API_KEY` for a runner-injected key. Fixed in `651e4f5` (`AGENTKIT_DOTENV_KEYS`) |
| A-LIVE-06 | Claude (AI-assisted) / 2026-10-14 | `651e4f5` | `live-llm-deepseek-2026-10-14b` | `.env` as is | **PASS**: 12 of 12 | deepseek_flash:deepseek-flash (12) | 0.025 | each cheap draft passed the claim audit |
| A-LIVE-07 | Claude (AI-assisted) / 2026-10-14 | `a04b879` before the grader fix | `live-llm-models-2026-10-14` | `.env` as is | **FAIL, then PASS**: 11 of 12; re-graded from the saved files: 12 of 12 | deepseek_flash:deepseek-flash (12), deepseek:deepseek-v4-pro (1, t12 escalated) | 0.036 | t10 failed `no_geometry_claim` on a true disclaimer ("Nothing in this answer comes from a geometry diff ..."): the check did not know "nothing" as a negation. Fixed in `a04b879`; the agent was correct |
| A-LIVE-08 | Claude (AI-assisted) / 2026-10-14 | `5fed6bd` | `live-llm-claude-gemini-2026-10-14` | `DEEPSEEK_API_KEY` and `OPENAI_API_KEY2` blanked for the process | **PASS**: 12 of 12 | anthropic_haiku:claude-haiku-5-5 (12), anthropic:claude-sonnet-5-5 (1, t05 escalated) | 0.030 | the Anthropic rows end to end |
| A-LIVE-09 | Claude (AI-assisted) / 2026-10-14 | `5fed6bd` | `live-llm-gemini-2026-10-14` | also `ANTHROPIC_API_KEY` blanked | **PASS**: 12 of 12 | gemini_lite:gemini-3.5-flash-lite (12) | 0.004 | the Gemini rows end to end (free-tier `GEMINI_API_KEY_2`) |
| A-LIVE-10 | Claude (AI-assisted) / 2026-10-14 | `ea0c797` (tier order OpenAI, DeepSeek, Moonshot, Gemini, Anthropic) | `live-llm-openai-first-2026-10-14` | `.env` as is | **PASS**: 12 of 12 | openai_luna:gpt-6-luna (12) | 0.004 | each cheap draft passed the claim audit |
| A-LIVE-11 | Claude (AI-assisted) / 2026-10-15 | `1963929` | `live-template-2026-10-15` | `.env` as is, `--skip-llm` | **PASS**: 12 of 12 | none (template answers) | 0 | the $0 baseline for the cost-vs-accuracy table (G12, `docs/COST_ACCURACY.md`) |
| A-LIVE-12 | Claude (AI-assisted) / 2026-10-15 | `1963929` + I4/I7/I11 (before the filing-denial fix) | `live-citations-2026-10-15` | `.env` as is | **PASS**: 12 of 12 | openai_luna:gpt-6-luna (12), openai_sol:gpt-6.1-sol (1, t12 escalated) | 0.012 | 7 `[@path]` citations, none wrong, none shown. t12 escalated because the claim audit read "No hand-offs have been filed." as a filing claim (the grader had the same rule); fixed |
| A-LIVE-13 | Claude (AI-assisted) / 2026-10-15 | with the filing-denial fix | `live-citations-2026-10-15b` | `.env` as is | **PASS**: 12 of 12 | openai_luna:gpt-6-luna (12) | 0.004 | no escalation |
| A-LIVE-14 | Claude (AI-assisted) / 2026-10-16 | branch `feat/server-runner-real-agent` | `python -m harness.runner --instance suryodaya` (local mode) | `.env` as is | **PASS**: 118 of 118 entries (7 platform checks, 8 agent tasks, 103 checks), 173 s | runner's own: openai_luna (tier order) | — | the first live run of the official runner with our agent inside; before the TLS change the 7 platform checks failed on this workstation only (certifi vs the OS trust store) |
| A-LIVE-15 | Claude (AI-assisted) / 2026-10-16 | same | `python -m harness.runner --instance keystone` | `.env` as is | **PASS**: 79 of 79 entries (4 agent tasks), 118 s | — | — | |
| A-LIVE-16 | Claude (AI-assisted) / 2026-10-16 | same | `python -m harness.runner` (server mode: injected `AGENTSWITCH_*` and `OPENAI_*`, no `--instance`) | token login, injected OpenAI key | **PASS**: 118 of 118 entries, 169 s | openai:gpt-4o-mini (the injected endpoint, first as on the server) | — | the agent used the runner's token (token mode) and the injected LLM, as the server will |
| A-LIVE-17 | Claude (AI-assisted) / 2026-10-16 | branch `feat/server-runner-real-agent` + goldens | `python -m harness.runner --instance suryodaya` | `.env` as is | **PASS**: 145 of 145 entries (27 goldens), 211 s | openai_luna (tier order) | — | the live shared platform still agrees with the seed-data goldens |
| A-LIVE-18 | Claude (AI-assisted) / 2026-10-16 | same | `python -m harness.runner --instance keystone` | `.env` as is | **PASS**: 91 of 91 entries (12 goldens), 128 s | — | — | |

Each provider row was also called once through the gateway (`GATEWAY_OK`) and listed `ok` by
`python -m agentkit.llm.models_check`. Not answering on 2026-10-14: `GEMINI_API_KEY` (HTTP 402, credit used up),
Cerebras (402), NVIDIA (`NVIDIA_MODEL` retired, 410); Gemini 3.5-3.8 Flash on the free key (503, busy).

- [ ] **A-LIVE-05** -- *To author:* offline test: after `load_env()` copies `OPENAI_API_KEY` from a temporary
  `.env`, a child process (simulate it: keep `os.environ`, clear `agentkit.config._FROM_DOTENV`, call
  `load_env()` again) still gets `from_process("OPENAI_API_KEY") is None`.
- [ ] **A-LIVE-12** -- *To author:* offline test: the grader's filing check and the claim audit
  accept "No hand-offs have been filed." and still reject "I filed the escalation; no further action is needed."
- [ ] **A-LIVE-07** -- *To author:* offline test: `geometry_claims("Nothing in this answer comes from a geometry
  diff.")` is empty; `geometry_claims("The geometry comparison shows a thicker wall.")` is not.
