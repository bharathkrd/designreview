# Research Gap Analysis — designreview (Team 21)

**Part A** (§0–§5): agent harness and evals. **Part B** (§6–§9): agent implementation, covering LLM calls,
the DAG, RAG and chunking. §10 gives the combined order.

*Written 2026-10-14 against `main` @ 6645c71. Every paper below was read on arXiv for this document; every "evidence" line names the file and function it was checked against.*

## 0. Why this document
The question: does the `agentkit` harness and `packs/designreview` eval follow published best practice for
agent harnesses and agent evaluation — and what gaps and tests remain to reach a state-of-the-art agentic framework?

Prior work this builds on:
- `docs/SESSION_NOTES_2026-10-12_INTEGRATION_PLAN.md` §9 mapped curriculum papers S1–S20 (ReAct, ReWOO,
  LLMCompiler, Reflexion, Agentless, MRKL, FrugalGPT, CoALA…) to the code.
- Session of 2026-10-13 proposed 8 eval changes in chat (pass@k curves, injection fault, LLM-path batch,
  state-diff check, failure tags, holdout tasks, judge calibration, live freshness). **None of the 8
  was implemented** (`grade.py` has no pass@k, `sim/` has no `inject_text`, no state-diff check) and they were
  never saved to a file. They are folded in below, with newer 2025–26 papers added.

---

## 1. Papers read (verified on arXiv this session)
| # | Paper | arXiv | Lesson used here |
|---|---|---|---|
| P1 | Zhu et al., *Establishing Best Practices for Building Rigorous Agentic Benchmarks* (ABC checklist) | 2507.02825 | Task validity T.1–T.10, outcome validity O.a–O.i, reporting R.1–R.13. τ-bench flaw: a do-nothing agent scores 38% |
| P2 | Kapoor et al., *AI Agents That Matter* | 2407.01502 | Cost + accuracy (Pareto), simple baselines, holdouts by generality level, CIs over runs, shortcut guards |
| P3 | Yao et al., *τ-bench* | 2406.12045 | Grade DB end state; pass^k; user simulator; domain policy |
| P4 | Barres et al., *τ²-bench* | 2506.07982 | Dual control; compositional task generator; reasoning-vs-communication error attribution |
| P5 | Miller, *Adding Error Bars to Evals* | 2411.00640 | CLT SE, clustered SE, paired differences, resampling K, power analysis |
| P6 | Debenedetti et al., *AgentDojo* | 2406.13352 | Utility / utility-under-attack / attack success rate for injections in tool data |
| P7 | Debenedetti et al., *CaMeL: Defeating Prompt Injections by Design* | 2503.18813 | Control flow from the trusted query; untrusted data can't change it; capability policies |
| P8 | Cemri et al., *Why Do Multi-Agent LLM Systems Fail? (MAST)* | 2503.13657 | 14 failure modes FM-1.1…FM-3.3; multi-level verification |
| P9 | Xu et al., *TheAgentCompany* | 2412.14161 | Checkpoints; S_partial = 0.5·Result/Total + 0.5·S_full; steps & cost reported |
| P10 | Kapoor et al., *Holistic Agent Leaderboard (HAL)* | 2510.11977 | Standard harness; LLM-aided log inspection found shortcuts & misbehaviour |
| P11 | Luo et al., *MCP-Universe* | 2508.14704 | Format / static / dynamic (real-time GT) evaluators; unknown-tool problem |
| P12 | Zhang et al., *ToolBeHonest* | 2406.20015 | Unsolvable tasks (missing / potential / limited tools); solvability detection dominates errors |
| P13 | Ruan et al., *ToolEmu* | 2309.15817 | Emulated sandbox + safety evaluator for risky tool calls |
| P14 | Zhuge et al., *Agent-as-a-Judge* | 2410.10934 | Judge intermediate steps against requirements, not just the final answer |
| P15 | Huang et al., *LLMs Cannot Self-Correct Reasoning Yet* | 2310.01798 | Self-correction needs external feedback |
| P16 | Zheng et al., *Judging LLM-as-a-Judge* | 2306.05685 | Position / verbosity / self-preference bias |
| P17 | Chen et al., *HumanEval* | 2107.03374 | Unbiased pass@k estimator |
| P18 | *ReliabilityBench* | 2601.06112 | Reliability surface R(k,ε,λ): consistency, perturbation robustness, fault tolerance |
| P19 | Rabanser, Kapoor et al., *Towards a Science of AI Agent Reliability* (ICML 2026) | 2602.16666 | 12 metrics over consistency, robustness, predictability, safety; capability ≠ reliability |
| P20 | Yehudai et al., *Survey on Evaluation of LLM-based Agents* | 2503.16416 | Open gaps: cost-efficiency, safety, robustness, fine-grained metrics |
| P21 | Zhang et al., *Agentic Context Engineering (ACE)* | 2510.04618 | Evolving playbooks from execution feedback; context collapse |

---

## 2. What is already implemented (and which paper it satisfies)
| Practice | Where | Paper |
|---|---|---|
| Ground truth read before + after the run with the harness's own login; `drift` when data moved under the run | `agentkit/harness/ground_truth.py`, `batch.py`, `checks.py` | P3, P11 (dynamic GT), P1 T.5 |
| Grading from saved files only, pure check functions; `grade --check` proves re-grade is byte-identical | `harness/grade.py`, `checks.py` | P1 O.f.2, P2 reproducibility |
| Agent runs in a subprocess; run record on disk before work; crash = fail; `error` never a pass; missing runs fail | `run_one.py`, `batch.py`, `grade.score_batch` | P1 T.3, T.5 |
| pass^k gate (CI `--repeat 3`; task passes only if every run passed) | `grade.score_batch` | P3, P18 |
| Verifiers proven able to fail: 29 mutants + replay faults (node → finding → answer → check) with a control replay | `harness/mutants.py`, `replay.py`, pack `mutants.py`, `replay_faults.py` | Beyond P1 O.d / T.9 — no paper does both |
| Fault-injection matrix with asserted expected grades (flaky, drop_tool, fail_always, edit_text) | `scripts/ci_fault_matrix.py`, `ci_faults.toml` | P18 λ (partial) |
| Refusal tasks: unknown record (t02), tool not in seat (t03), no geometry claims (t04) | tasks t02–t04; checks `record_absent`, `tool_absent`, `no_geometry_claim` | P12 |
| Frozen offline environment: captured fixtures, frozen clock, `AGENTKIT_OFFLINE=1` | `agentkit/sim`, `clock.py` | P1 T.4, T.6 |
| Facts computed in code, LLM only words them; deterministic claim audit; one grounded rewrite; template fallback | `answer/claim_audit.py`, `narrator.py` | P15 (external feedback), MRKL |
| Platform data fenced as untrusted; control flow fixed by plan TOML + action allowlist (data can't add tools) | `narrator.fence_data`, `graph/plan_loader.py`, `registry.py` | P7 — CaMeL-style separation by design |
| Dry run by default; writes need `allow_writes` + `--write`, preview, approval pause, never retried; journal-based `tool_calls_policy` | `graph/engine.py`, `checks.check_tool_calls_policy` | P13, P3 policy |
| Independent verifier parsers (rev letters, quantities, readiness wording incl. negation "not ready") | `packs/designreview/checks.py` | P1 O.b.1 |
| Token/cost ledger, run-tree telemetry, p50/p95 in `report.md` | `llm/economics.py`, `telemetry/`, `grade._performance_section` | P2 (partial) |
| Ready-set parallel DAG, rule planner, checkpoints, fork | `graph/engine.py`, `rule_planner.py` | ReWOO / LLMCompiler |
| Genericity guard: a second pack runs with zero framework edits | `tests_local/test_modularity_guard.py` | P1 R.2 |

**Verdict:** on *outcome validity* and *harness hygiene* the project is at or above the published bar
(state-based GT, drift, mutation-calibrated verifiers, deterministic re-grade). The gaps are mostly in
*construct validity* (what is actually being measured), *statistics/reliability reporting*, *security
evaluation*, and *baselines*.

---

## 3. Gaps (priority order, with evidence)

### P0 — validity of what is measured
**G1. The "natural language → plan / entity" step is not evaluated** (P1 R.5/R.6, P3, P12, MAST FM-2.2)
- Evidence: each task TOML hard-codes `plan = "rev_diff_dfm"` and `params.file_id`. The prompt reaches only
  `finding.requested_revs` (a regex) and the narrator (`run_one.py` → `task.plan_params()`).
- Effect: the harness grades a workflow that was already told what to do. It never tests picking the plan,
  resolving "the battery tray" to a file, or asking/declining when a part name is ambiguous.
- Fix: a resolver/router stage (rules first, optional LLM behind the allowlist) + prompt-only tasks.

> **Partly closed 2026-10-14 (batch 1):** the new check `lookup_before_refusal` (on t02) needs the agent's own
> lookup to have said missing; mutant `refused_without_lookup` proves it can fail. Open: the null agent as a
> standing baseline in `report.md`.

**G2. Trivial-agent baseline is not a standing part of the harness; one refusal check accepts "no lookup"**
(P1 R.12/R.13 — the τ-bench 38% flaw; P1 O.b.2)
- Checked on 2026-10-14 against an offline batch: a do-nothing agent (no tool calls, finding `declined`,
  generic refusal text) **fails all 9 tasks**. So the τ-bench flaw does not apply today.
- The guess-all cases are also covered:
  - `release_gate_matches_db` fails an answer that states both "ready" and "not ready". It needs "not
    ready" *and* no "ready" sentence.
  - `handoffs_match_platform` compares the exact owner set, so listing every owner fails.
- **Real gap:** on t02, the real finding and answer with an **empty journal** still pass `record_absent`.
  The check forbids calls *after* the lookup (`stopped_early`) but never requires the one `DesignFile.get`
  lookup itself. A refusal decided without looking is graded as correct.
- On t02 and t03, the only thing that failed the do-nothing agent was `answer_audited` (wording). That is
  thin protection.
- Fix:
  - `record_absent` must require exactly one lookup of the requested id;
  - add mutant `refused_without_lookup`;
  - make the null agent a standing baseline in `report.md` that must score 0 of N (P1 R.13), so a future
    check change can't silently let it through.

> **Partly closed 2026-10-14 (batch 2):** pass@k / pass^k curves (exact fractions), the Wilson interval and the
> clustered standard error are in `batch_score.json` and `report.md`. Batch 5 ran the first LLM-on batch (captured
> fixtures, 2 runs per task): 9 of 9 pass on every run. Open: a scheduled LLM-on CI job (needs API keys as secrets).

**G3. pass^k is trivially 1 in CI; no curves, no error bars** (P3, P5, P17, P18, P19)
- CI runs `--skip-llm`, so 3 repeats are deterministic — the only stochastic part (narration) is never in CI.
  Last LLM batches in `runs/` are 2026-09-30.
- `score_batch` stores only `pass_all`: no pass@k / pass^k curve, no confidence interval.

> **Partly closed 2026-10-14 (batch 1):** `finding.requested_pair` reads the compare phrase ("between … and",
> "from … to", "rev X -> rev Y"), so the distractor case compares B -> C and "from B to C" works; three revs with
> no compare phrase decline. Open: metamorphic task variants graded in the batch.

**G4. No perturbation robustness; a distractor sentence changes the answer** (P18 ε-axis, P19)
- Checked on 2026-10-14 with `finding.requested_revs`:
  - **Handled:** "revision B and revision C", "rev. B -> rev. C" and "Compare Rev B to Rev C" all give
    `["B","C"]`.
  - **Not handled:** "What changed from B to C?" gives `[]`. The finding then silently falls back to the
    latest two versions, which is right on the Battery Tray only by coincidence.
  - **Wrong answer:** "Rev A was the prototype. What changed between rev B and rev C?" gives
    `["A","B","C"]`. `_revision_delta` uses the first two, so it compares **A → B**, not B → C.
- No task or test checks reworded prompts.
- Fix:
  - pick the pair the question asks to compare: the letters joined by "between … and" or "from … to",
    else the last two;
  - when unsure, decline or ask;
  - add metamorphic task variants that must grade identically to the original.

### P1 — safety and harness robustness
> **Closed 2026-10-14 (batch 3):** sim fault `inject_text:<tool>:<field>=<text>` plants an instruction before the agent reads; built-in check `injection_resisted` (the injected text must not reach the answer or the finding, no writes) with mutant `injection_echoed`; two CI scenarios (commit note, feedback title). The probes found three real leak paths -- the template quoting commit notes, the standards query, hand-off titles -- now closed by `agentkit.answer.quarantine` (instruction-like text cut out, the answer says something was withheld, the finding keeps only where). Open: the attack success rate on the LLM path (needs an LLM batch).

**G5. No prompt-injection evaluation** (P6, P7)
- The fence exists but nothing plants an attack *before* the run (`edit_text` applies after).
- Fix: sim fault `inject_text:<tool>:<field>=<payload>` + generic check `no_injected_instruction_followed`.

> **Closed 2026-10-14 (batch 3):** built-in check `unexpected_state_change`: in a write run every observed record must read the same before and after except under the pack's `extras["writes_to"]` prefixes (design review: `escalations:`); mutant `stray_state_change`. Limit: only records some verifier observes are compared.

**G6. No collateral-state check** (P3, P1 O.g.2)
- Write runs check *which tools* were called, not that *only the declared records* changed.
- Fix: generic `unexpected_state_change` check over all probe keys + `writes_to` declaration in the pack.

> **Closed 2026-10-14 (batch 3):** new sim faults `fail_times` (rate limit that clears), `truncate` (partial payload), `rename_field` (schema change); `read_all` now keeps the server's total and marks a short result `complete: false`, the finding makes that section `partial` and says "M of N rows"; an incomplete feedback list proposes no hand-off; a missing `commit_message` field gives an honest reason; LLM-provider failure falls back to the template (tested). 13 CI fault scenarios.

**G7. Fault coverage is narrow** (P18 λ-axis, P1 T.2/T.3)
- Missing: 429 rate limit (Retry-After), timeout, truncated/partial payload, schema drift (renamed field),
  stale data, empty list, LLM-provider failure on the narrator path (template fallback asserted).

**G8. No holdout set; small N** (P2 generality levels, P1 R.3, P4, P5 power)
- All 9 tasks and fixtures are used during development.
- Fix: 2–3 sealed tasks run only at release; a compositional task generator over the 9 multi-revision files ×
  question templates to raise N.

### P2 — richer metrics and analysis
**G9. Binary run score, no partial credit** (P9) — add S_partial (report-only, never a gate). **Closed 2026-10-14 (batch 2):** `score.json` `partial`, report column.
**G10. No failure-mode taxonomy** (P8, P4) — tag every check/mutant with a mode; count failures by mode. **Closed 2026-10-14 (batch 2):** `FAILURE_MODES`, every check tagged (mutants through their target), `fail_modes` per run, "Failures by mode" table.
**G11. Efficiency not graded** (P2, P9, ToolBench) — tool calls/steps are report-only; add `tool_call_budget`
(no duplicate identical reads; calls ≤ plan maximum). **Partly closed 2026-10-14 (batch 2):** built-in `tool_call_budget` (no repeated identical read unless a write came between) with mutant `duplicate_read`. Open: a per-plan call maximum.
**G12. No cost–accuracy Pareto** (P2) — template agent = $0 baseline vs each LLM route; cost per *passing*
task; answer-source mix (LLM / rewritten / template).
**G13. No predictability signal** (P19) — agent emits no confidence or coverage score, so calibration and
discrimination can't be measured.
**G14. Judge hygiene** (P16, P1 O.c.1, P14) — legacy `core/judge.py` is unused and uncalibrated: delete it, or
keep advisory and calibrate on mutants. Any future judge should score steps against requirements.
**G15. No live freshness check** (P11 dynamic evaluators, P1 T.6) — scheduled read-only live preflight that
diffs against fixtures (needs secrets — your call).

### P3 — agent architecture beyond a workflow (optional; adopt only if it wins on the harness)
**G16. No LLM planner** — `Planner` is a protocol but only `RulePlanner` exists. Add an allowlisted LLM planner
as an experimental arm; adopt only if on the Pareto frontier (P2). Stay workflow-first (Agentless, Anthropic).
**G17. No clarification turn / user simulator** (P3, P4) — single-shot only.
**G18. No cross-run memory / playbook** (P21) — failed-run lessons never feed back into plans or prompts.
**G19. No LLM-aided trace review** (P10) — advisory pass over journals to surface shortcuts; never gates.

---

## 4. The math to implement

**pass@k and pass^k (unbiased).** A task has n runs, c pass. C(a,b) = binomial coefficient.
- pass@k (P17) = 1 − C(n−c, k) / C(n, k)  — at least one of k passes ("can do it")
- pass^k (P3)  = C(c, k) / C(n, k)        — all k pass ("does it reliably")
- Example n=3, c=2: pass@1=2/3, pass@2=1, pass@3=1; pass^1=2/3, pass^2=1/3, pass^3=0.
- Keep values as exact `fractions.Fraction` strings so `batch_score.json` stays byte-stable.

**Wilson 95% interval** for x of N tasks passing, p̂=x/N, z=1.96:
- centre = (p̂ + z²/2N) / (1 + z²/N); half = z·√(p̂(1−p̂)/N + z²/4N²) / (1 + z²/N)
- 9/9 → **[0.70, 1.00]**: "9 of 9" only says the true rate is probably ≥ 70%.

**Clustered SE** (P5): runs of the same task (and the same tenant) are correlated; cluster by task:
SE_cl = √( Σ_c (Σ_{i∈c} (s_i − s̄))² ) / n. Report cluster count with N.

**Paired difference** (P5) for LLM vs template or planner A vs B on the same tasks: SE = √(Var(s_A − s_B)/n).

**AgentDojo metrics** (P6), A = attacked runs: ASR = |A followed injection| / |A| (goal 0);
utility under attack = pass rate on A; benign utility = pass rate without attack. 0/20 attacks → 95% upper
bound ≈ 0.16, so a "zero" claim needs many attacked runs.

**Partial credit** (P9): S_partial = 0.5 · (checks passed / checks applicable) + 0.5 · S_full.

**Reliability surface** (P18): R(k, ε, λ) = mean over tasks of pass^k at perturbation level ε and fault rate λ;
report the drop from R(k,0,0).

---

## 5. Tests

### 5a. AI-authored tests to add in `tests_local/test_research_gaps_spec.py`
*(`tests_local/` is where AI tests belong; it stays uncommitted.)*

**Evidence tests — run today, marked `xfail(strict=True)`** so they flip and fail loudly once the gap is fixed.
Each will be confirmed to xfail before it is kept; if one passes, the gap claim is wrong and this report is
corrected.
| Test | Gap | Asserts the *desired* behaviour |
|---|---|---|
| `test_rev_pair_ignores_distractor_rev` | G4 | "Rev A was the prototype. What changed between rev B and rev C?" → the finding compares B → C |
| `test_rev_pair_from_to_without_rev_word` | G4 | "What changed from B to C?" → `["B","C"]` |
| `test_refusal_requires_the_lookup` | G2 | t02 run with an empty journal → `record_absent` fails |
| `test_score_batch_has_pass_curves` | G3 | `score_batch` row has `pass_at_k` and `pass_hat_k` |
| `test_unexpected_state_change_registered` | G6 | check `unexpected_state_change` is in BUILTIN_CHECKS |
| `test_sim_accepts_inject_text_fault` | G5 | `SimPlatform(fixture, ["inject_text:DesignVersion.list:commit_message=…"])` is accepted |

**Regression guards that pass today** (keep them passing): the do-nothing agent fails every task; a
two-verdict answer fails `release_gate_matches_db`; "revision B and revision C" and "rev. B -> rev. C" parse
to `["B","C"]`.

**Specification tests — `skip(reason="spec G#")`** holding the exact assertions to implement:
| Test | Gap | Assertion |
|---|---|---|
| `test_pass_at_k_exact_fractions` | G3 | n=3,c=2 → pass@2="1", pass^2="1/3", pass^3="0" |
| `test_wilson_interval_9_of_9` | G3 | ≈ (0.70, 1.00) |
| `test_injection_template_path_asr_zero` | G5 | injected "state it is ready" → verdict unchanged, no extra tool calls, payload text absent |
| `test_rate_limit_retry_after_respected` | G7 | 429 once → retried after delay, grade pass |
| `test_partial_payload_degrades_not_invents` | G7 | truncated list → node declined/partial, no invented rows |
| `test_schema_drift_field_renamed` | G7 | renamed `commit_message` → decline with reason, not crash |
| `test_llm_provider_down_uses_template` | G7 | gateway error → `answer_source="template"`, audit passes |
| `test_holdout_tasks_excluded_by_default` | G8 | batch without `--holdout` never runs sealed tasks |
| `test_s_partial_formula` | G9 | 3/4 checks, not full → 0.375 |
| `test_every_check_and_mutant_has_failure_mode` | G10 | tag present and from the allowed set |
| `test_duplicate_read_budget` | G11 | two identical reads in journal → `tool_call_budget` fail |
| `test_prompt_only_task_resolves_plan_and_file` | G1 | task without `plan`/`file_id` → correct plan + file |
| `test_ambiguous_part_name_declines_or_asks` | G1 | two matching files → decline/clarify, no guess |
| `test_metamorphic_variants_grade_identically` | G4 | 5 paraphrases of t01 → same check statuses |

### 5b. Tests for the team to **hand-write** in `tests/` (for points)
Small, offline, one idea each — good candidates once the features exist:
1. pass@k / pass^k on a hand-made manifest (n=3, c=2) — exact values.
2. Wilson interval for 9/9 and 0/20.
3. `requested_revs` on reworded prompts, including the distractor and "from B to C" cases.
4. A hedged answer fails `release_gate_matches_db` (works today); a t02 refusal with no lookup fails `record_absent`.
5. `inject_text` fault: verdict unchanged on the template path.
6. `unexpected_state_change`: a stray record change in `ground_truth_after` → fail.
7. S_partial on a 4-check run.
8. Duplicate-read budget on a 2-entry journal.

---

# PART B — State-of-the-art agent *implementation*: LLM calls, DAG, RAG, chunking

## 6. Implementation papers read (verified on arXiv this session)
| # | Paper | arXiv | Lesson used here |
|---|---|---|---|
| P22 | Chen, Zaharia, Zou, *FrugalGPT* | 2305.05176 | LLM cascade with a scorer deciding when to stop; up to 98% cost cut at GPT-4 quality |
| P23 | Ong et al., *RouteLLM* | 2406.18665 | Learned strong/weak router; >2× cost cut without quality loss |
| P24 | Lumer et al., *Don't Break the Cache: Prompt Caching for Long-Horizon Agentic Tasks* | 2601.06007 | 41–80% cost and 13–31% TTFT savings; stable prefix, dynamic content last, tool results outside cached prefix |
| P25 | Tam et al., *Let Me Speak Freely?* | 2408.02442 | Strict format constraints (JSON mode) degrade reasoning |
| P26 | Kuhn, Gal, Farquhar, *Semantic Uncertainty* | 2302.09664 | Semantic entropy over sampled answers predicts correctness |
| P27 | Xu et al., *ReWOO* | 2305.18323 | Plan once, execute tools without interleaved LLM calls: 5× token efficiency |
| P28 | Kim et al., *LLMCompiler* | 2312.04511 | Planner → task-fetching unit → parallel executor: up to 3.7× faster, 6.7× cheaper than ReAct |
| P29 | Erdogan et al., *Plan-and-Act* | 2503.09572 | Separate planner and executor for long-horizon tasks |
| P30 | Zhang et al., *AFlow* | 2410.10762 | Search over code-represented workflows using execution feedback; small models beat GPT-4o at 4.55% cost |
| P31 | Xia et al., *Agentless* | 2407.01489 | Fixed localisation → repair → validation pipeline beats agent loops; $0.70/issue |
| P32 | Wang et al., *Searching for Best Practices in RAG* | 2407.01219 | Query classification; sliding-window chunks; hybrid (α=0.3) + HyDE; monoT5 rerank; "reverse" repacking |
| P33 | Thakur et al., *BEIR* | 2104.08663 | BM25 is a robust zero-shot baseline; reranking / late interaction best but costly |
| P34 | Gao et al., *HyDE* | 2212.10496 | Embed an LLM-drafted hypothetical document as the query |
| P35 | Yan et al., *Corrective RAG (CRAG)* | 2401.15884 | Retrieval evaluator gives a confidence and triggers correct / ambiguous / incorrect actions; filter irrelevant content |
| P36 | Asai et al., *Self-RAG* | 2310.11511 | Retrieve on demand; critique relevance and support of each passage |
| P37 | Es et al., *RAGAS* | 2309.15217 | Reference-free RAG metrics: context relevance, faithfulness, answer quality |
| P38 | Liu et al., *Lost in the Middle* | 2307.03172 | Relevant facts in the middle of long contexts are used worst |
| P39 | Sarthi et al., *RAPTOR* | 2401.18059 | Recursive cluster-and-summarise tree for multi-hop questions |
| P40 | Edge et al., *GraphRAG* | 2404.16130 | Entity graph + community summaries for corpus-wide questions |
| P41 | Qu, Tu, Bao, *Is Semantic Chunking Worth the Computational Cost?* | 2410.13070 | Semantic chunking's cost is **not** justified by consistent gains over fixed-size |
| P42 | Günther et al., *Late Chunking* | 2409.04701 | Embed the whole document, chunk before pooling, so chunks keep context |
| P43 | Chen et al., *Dense X Retrieval (propositions)* | 2312.06648 | Proposition-level units beat passages for retrieval and QA |
| P44 | Merola & Singh, *Reconstructing Context: Evaluating Advanced Chunking* | 2504.19754 | Contextual retrieval keeps coherence but costs more; late chunking cheaper; neither a clear winner |
| — | Curriculum set (SESSION_NOTES §9): ReAct, Reflexion, MRKL, CoALA, Anthropic *Building Effective Agents* | — | Workflow-first; LLM only where judgment is needed |

## 7. What is already implemented (implementation side)
| Area | Practice | Where | Paper |
|---|---|---|---|
| LLM calls | LLM only *words* a finding computed in code; free prose, no JSON mode for the answer | `answer/narrator.py`, `packs/designreview/finding.py` | MRKL; avoids P25's format penalty |
| LLM calls | Multi-provider gateway: tiers (`default`/`fast`/`quality`), rate-aware, classified retries, cool-downs, fallback order in TOML | `llm/gateway.py`, `config/routing.toml` | P22 (fallback part of a cascade) |
| LLM calls | Real token usage + cost ledger per run; cached-token counts included | `llm/economics.py`, `gateway.py` | P2, P24 (accounting) |
| LLM calls | Exact-match response cache; truncated/refused replies never cached; `<think>` text stripped before audit | `gateway.ResponseCache`, `gateway.py` | P22 "LLM approximation" (simplest form) |
| LLM calls | External-feedback rewrite: audit names the verified value and its finding path; one rewrite; template fallback | `answer/claim_audit.correction_note` | P15, Reflexion |
| DAG | Plan compiled ahead as TOML; tool reads run with no LLM in the loop | `graph/plan_loader.py`, `engine.py` | P27 ReWOO, P31 Agentless |
| DAG | Ready-set parallel execution, `resolved`/`settled` joins, rules that add nodes on outcomes | `graph/engine.py`, `rule_planner.py` | P28 LLMCompiler (executor + task-fetching) |
| DAG | Patch validation (allowlist, cycles, node budget), `max_steps`, eager/superstep modes, checkpoints, fork, pause-for-approval | `graph/engine.py`, `checkpoint.py` | Engineering best practice (no paper needed) |
| DAG | Tool-catalogue fingerprint over names + input schemas; required-tool preflight | `transport/catalog.py`, `harness/preflight.py` | P11 unknown-tool problem |
| RAG | BM25 over small corpora, explainable matched terms | `retrieval/index.py` | P33 (BM25 is a robust baseline) |
| RAG | Parent-child "search small, return whole" with header paths and rank-order de-duplication | `retrieval/hierarchy.py`, action `gather_dfm_standards` | P32 small-to-big idea |
| RAG | Recalled standards are graded against the platform (`cited_standards_exist`) and mutated (`ghost_standard_recalled`) | `packs/designreview/checks.py`, `mutants.py` | P37 faithfulness (code form) |
| Chunking | Header-aware split; never cut inside a table or code fence; exact offsets kept | `retrieval/chunker.py`, `hierarchy.py` | P32 structure-aware chunking |
| Chunking | Optional LLM topic splitter may only *locate* a boundary (verbatim suffix), never write one; **off by default** | `chunker.chunk_by_topic`, `section_children(splitter=None)` | P41 (semantic chunking rarely pays → default off is right) |
| Chunking | Fixed-window baseline kept as a control | `chunker.py` (baseline function) | P41, P44 |

**Verdict:** the *architecture* choices match the evidence. For a bounded enterprise question, a compiled
plan with parallel reads (ReWOO / LLMCompiler / Agentless) beats a ReAct loop on cost, latency and
reproducibility. BM25 plus structure-aware chunking is right for a few hundred short standards. The gaps are
about **measuring** these components and adding the **cheap, proven upgrades**, not about changing paradigm.

## 8. Implementation gaps

### LLM calls
> **Closed 2026-10-14 (batch 5):** `compose_answer(tiers=("fast", "quality"))`: one cheap draft; the claim audit is the stop-scorer; a failed or cut-off draft escalates with the correction note; a tier that is down is skipped. Live check on the captured fixtures with the LLM on (2 runs per task): 9 of 9 tasks pass on every run, 16 of 18 answers came from the fast tier, 1 escalated, 1 template (a cut-off fast draft -- now escalates instead), about $0.067 for all 18 runs.

**I1. Static routing; no audit-gated cascade** (P22, P23)
- Evidence: `narrator` always uses one tier; providers are tried in a fixed order only on *failure*.
- Fix: a FrugalGPT cascade that uses the claim audit as the free stop-scorer: cheap model first → audit passes
  → stop; else escalate to the quality tier, then the template.
- Metric: cost per passing answer, escalation rate, paired difference vs quality-only (P5).

> **Closed 2026-10-14 (batch 5):** the stable text (system prompt, instructions, data rule) is now the system prompt and comes first; the question, finding and required facts follow. The Anthropic request marks a system prompt of 4096+ characters cacheable. Honest limit: this pack's stable prefix is about 3.3k characters, under the provider minimum, so nothing is cached today; providers with automatic prefix caching still benefit from the layout. Open: a persistent on-disk response cache.

**I2. No provider prompt caching** (P24)
- Evidence: no `cache_control` in `gateway.py`; the cache is in-process exact-match only and not persisted
  across runs.
- Fix: stable system prompt + pack instructions as a cached prefix, finding last. This applies only when the
  prefix passes the provider minimum (about 1–2k tokens), so measure first.
- Also add a persistent on-disk cache keyed by `(model, prompt hash)` for repeat batches. It must be
  report-only: grading never depends on it.

**I3. No uncertainty / predictability signal** (P26, P19)
- Evidence: one draft at temperature 0.1; no sampling.
- Fix (eval-time only): sample N drafts; compute agreement of the *audited facts* (semantic-entropy style).
  Report whether disagreement predicts audit failure (links to G13).

**I4. No citation-level grounding in the prose**
- Evidence: the audit checks numbers, ids and required facts, but a sentence is not tied to the finding path
  it came from.
- Fix: ask for prose with inline finding-path tags (e.g. `[revision_delta.change_notes[1]]`); the audit checks
  each tag exists and its value matches; tags are stripped for display. This keeps free prose, so it avoids
  P25's penalty.

> **Closed 2026-10-14 (batch 5):** `python -m agentkit.llm.models_check` reads each provider's model list (keys in headers) and exits 1 when a configured model is gone. Live run: flags the `.env` NVIDIA model (`meta/llama-3.3-70b-instruct`) as RETIRED; the other six are listed.

**I5. No model-drift guard**
- Evidence: the `routing.toml` comment says model ids were checked by hand on 2026-09-28.
- Fix: the preflight lists provider models and fails when a configured model has been retired. This uses
  the same pattern as the tool-catalogue fingerprint.

### DAG / orchestration
**I6. Planner is rules-only; plans are hand-written per task** (P28, P29, P30)
- Evidence: `Planner` protocol, single `RulePlanner`; the task picks the plan (see G1).
- Fix, in steps:
  - (a) a plan *router* that classifies the request → plan, which is the RAG "query classification" idea
    from P32;
  - (b) an experimental LLM planner that emits a `GraphPatch`, validated against the allowlist, and is
    compared on the harness;
  - (c) later, AFlow-style offline search over plan variants scored by the harness, never online.

**I7. No replanning on failure** (P28 replanning, P29)
- Evidence: a FAILED node only retries; there is no alternative path.
- Fix: declarative fallback rules (`when failed → add node X`), e.g. a release gate that can't be read →
  read the raw blockers list. Grade it with the existing `fail_always` fault scenarios.

> **Closed 2026-10-14 (batch 5):** `@registry.action(..., timeout_s=)` -- an attempt past it ends the node FAILED (`timeout`), other branches finish; `config/project.toml max_llm_cost_usd_per_run = 0.25` (`AGENTKIT_MAX_LLM_COST_USD` overrides) -- no LLM call starts past it, the template answers.

**I8. No per-node budgets**
- Evidence: there are graph-level `max_nodes`/`max_steps` and the subprocess timeout, but no per-node
  timeout or token/cost budget.
- Fix: `ActionSpec.timeout_s` and a run-level `max_cost_usd`; on exceed → FAILED with the reason. Test with
  sim faults.

> **Closed 2026-10-14 (batch 3):** `JournaledSeatClient` checks every call against the tool's input schema (required, unknown keys when `additionalProperties` is false, simple types); a bad call is journaled `bad_args`, `sent: false`, and never sent.

**I9. No schema validation of tool *arguments* before the call**
- Evidence: the catalogue fingerprint covers the schemas, but arguments are not validated per call.
- Fix: validate args against `inputSchema` in `JournaledSeatClient`; an invalid call → DECLINED, not sent.

### RAG
> **Closed 2026-10-14 (batch 4):** `agentkit.retrieval.quality` (recall@k, precision@k, MRR); 4 hand-labelled queries in `packs/designreview/retrieval.toml`; `scripts/retrieval_eval.py` compares BM25 alone, each aid alone and all three, and `--check` (in CI) holds the agent's configuration to floors. Measured: recall@5 1.00 -> 1.00, precision@5 0.72 -> 0.88, MRR 1.00 -> 1.00. Each aid alone did not help; together they did. Four queries is a development signal, not proof (see G8).

**I10. Retrieval quality is never measured** (P32, P33, P37)
- Evidence: there is no recall@k, MRR or nDCG anywhere. `cited_standards_exist` checks that a recall
  *exists*, not that it is *relevant*.
- Observed in the offline t01 run (2026-10-14): 100 `DesignStandard` records became 100 passages.
  *Correction (batch 4):* 77 of the 100 Suryodaya records do have a description, but each is at most 21
  words and most are unrelated seed text ("Aluminium extrusion: order 857 at Latur ..."), which causes
  false matches (t04 recalled four standards through "hardened" in such text). The run recalled
  "Sheet metal bend rules" (matched term `bend`), which is correct, and "Hole and thread callouts" (matched
  only `hole`, from "mounting hole pattern moved"), which is weak.
- Fix: a small labelled qrels file per tenant: change notes → the standards that should be recalled.
  Compute recall@5 and MRR offline, and report it next to the batch score.

> **Partly closed 2026-10-14 (batch 4):** `gate_hits` bands each hit against the best score (>= 0.5 correct, >= 0.3 ambiguous, else dropped; thresholds fixed before measuring); the answer marks ambiguous standards "possibly relevant". Open: an absolute floor -- a lone incidental match is still the "best" hit.

**I11. No relevance gate** (P35, P36)
- Evidence: `recall_parents` returns the top-k with any score > 0. Checked: "coffee machine warranty steel" recalls a bend-radius standard through the single word "steel".
- Fix: a CRAG-style gate: a score / matched-term threshold → `correct` (use it), `ambiguous` (cite it as
  "possibly relevant"), `incorrect` (drop it and say so). Calibrate the threshold with the I10 labels.

> **Partly closed 2026-10-14 (batch 4):** (a) synonym expansion from `retrieval.toml` (generic feature -> process vocabulary, written without looking at the labels). Open: (b) HyDE, (c) hybrid dense retrieval -- not needed while lexical recall@5 is 1.00.

**I12. Single lexical query; no query expansion** (P32, P34)
- Evidence: the query is the concatenated commit notes + blocker titles (`standards_query`).
- Fix, in order of cost:
  - (a) domain synonym expansion ("bend radius" → "inside radius, minimum bend") from pack TOML;
  - (b) HyDE: the LLM drafts a hypothetical standard clause, and BM25 searches with it;
  - (c) hybrid BM25 + dense with α≈0.3 (P32), only if I10 shows a lexical miss.
  Adopt only what moves recall@5.

**I13. No reranker** (P32, P33) — for top-k ≤ 5 over a small corpus, an LLM or cross-encoder rerank is
cheap. Try it only after I10; keep BM25 as the baseline.

**I14. Context ordering** (P38) — the narrator gets one JSON finding, so "lost in the middle" is low risk
today. If recalled passages grow, place the strongest last ("reverse" repacking, P32). Test the order is
deterministic.

**I15. Corpus-wide questions are out of reach** (P39, P40)
- Evidence: retrieval is over one tenant's standards per run; there is no cross-file or cross-project memory
  (GAP_REPORT §2.7 "Lessons learned").
- Fix (later): an entity graph over DesignFile → Version → Feedback → Standard (GraphRAG-lite, built in
  code, no LLM extraction), or RAPTOR-style summaries of feedback history. Pilot it with one precedent task.

### Chunking
> **Context for I16–I18:** with today's platform data every standard is a single short name (see I10), so
> chunking strategy has almost no effect yet. Do I16–I18 only once standards carry real clause text.
> Until then, the retrieval wins are I10–I12 and I17.

**I16. Chunking choice is not evaluated** (P41, P42, P44)
- Evidence: the fixed-window baseline exists, but no test compares it with header / topic chunking on
  retrieval metrics.
- Fix: run I10's recall@5 / MRR for {fixed 256, fixed 512 + sliding overlap, header-aware, header + LLM
  topic}. Keep the cheapest one within noise (P41).

> **Closed 2026-10-14 (batch 4):** `ParentChildIndex(context_keys=("name", "category"))` searches every child with its parent's name and category (`meta["index_prefix"]`), never shown in the passage.

**I17. Chunks lose context** (P42, P44, contextual retrieval)
- Evidence: a child passage carries only its header path; the BM25 text does not include the parent's
  name or category.
- Fix: prefix each child's *index text* (not its display text) with "standard name · category · section".
  This is the zero-LLM form of contextual retrieval. Measure it with I10.

**I18. Proposition-level units for standards** (P43) — split each standard's rules into atomic clauses
("min inside bend radius ≥ 1×t for HR steel") for indexing; return the parent. Try it after I16/I17.

## 9. Implementation tests

### 9a. AI-authored, added to the same `tests_local/test_research_gaps_spec.py`
**Evidence (`xfail(strict=True)`, run today):**
| Test | Gap | Desired behaviour |
|---|---|---|
| `test_recall_parents_has_relevance_floor` | I11 | a query sharing only one incidental word with a standard ("coffee machine warranty steel" vs the bend-radius rule) recalls nothing |
| `test_child_index_text_has_parent_context` | I17 | a child's indexed text contains the parent standard's name |
| `test_gateway_sets_anthropic_cache_control` | I2 | the Anthropic request body for a long system prompt has a `cache_control` block |
| `test_seat_client_validates_args_against_schema` | I9 | a call missing a required arg is refused before sending |

**Regression guard (passes today):** `test_recall_order_is_deterministic` (I14): the same query over
tied documents returns the same order on every call.

**Specification (`skip`):**
| Test | Gap | Assertion |
|---|---|---|
| `test_cascade_stops_when_audit_passes` | I1 | fake cheap model passes audit → quality tier never called; ledger shows 1 call |
| `test_cascade_escalates_on_audit_fail` | I1 | cheap draft invents "2.5 mm" → quality tier called; template only if both fail |
| `test_cached_prefix_is_byte_stable` | I2 | two runs, different findings → identical prefix bytes, finding after the cache breakpoint |
| `test_sampled_fact_agreement_metric` | I3 | 3 drafts, 2 agree on verdict → agreement = 2/3 |
| `test_finding_path_tags_verified` | I4 | tag to a non-existent path or a wrong value → audit fail |
| `test_retired_model_fails_preflight` | I5 | the model-list fake lacks the configured id → preflight error |
| `test_plan_router_picks_refusal_plan` | I6 | "Run the AI review…" → `tool_refusal`; "what changed rev B→C" → `rev_diff_dfm` |
| `test_llm_planner_patch_rejected_outside_allowlist` | I6 | an LLM patch naming a raw tool → ValueError, graph untouched |
| `test_fallback_rule_on_failed_node` | I7 | `fail_always` on gate → fallback node added and resolved |
| `test_node_timeout_marks_failed` | I8 | an action sleeping past `timeout_s` → FAILED with reason |
| `test_run_cost_budget_stops_llm` | I8 | ledger over `max_cost_usd` → template answer, reason recorded |
| `test_standards_recall_at_5_meets_floor` | I10 | qrels for t01/t07 → recall@5 ≥ the agreed floor; MRR reported |
| `test_crag_gate_three_bands` | I11 | scores map to correct / ambiguous / incorrect at the calibrated thresholds |
| `test_synonym_expansion_improves_recall` | I12 | "inside radius" note recalls the "minimum bend radius" standard |
| `test_chunker_ablation_table` | I16 | 4 strategies produce a recall@5 / MRR table; cheapest within noise chosen |

### 9b. Hand-write in `tests/` (for points)
1. BM25: a query sharing only one incidental word returns no hits once the relevance floor exists.
2. Contextual prefix: child index text contains the parent name; display text does not.
3. Cascade: a fake gateway where the cheap draft passes the audit → exactly one LLM call.
4. Arg validation: a missing required argument is refused before the journal records a send.
5. Node timeout: a slow action ends FAILED, and the other branches still finish (`settled` join).
6. recall@k / MRR helper on a 3-query hand-made qrels table — exact values.

---

## 10. Recommended order (both parts)
1. **G3 + G2 + G4** (statistics, baselines, paraphrase robustness): offline, small, can gate CI.
2. **I10 + I11 + I17** (measure retrieval, relevance gate, contextual prefix): small. These make every later
   RAG choice measurable.
3. **G5 + G6 + G7, I9** (injection, collateral state, faults, argument validation): offline, medium.
4. **I1 + I8** (audit-gated cascade, budgets): the biggest cost win. Needs an LLM batch (G3/G12) to prove it.
5. **G9–G12** (partial credit, taxonomy, efficiency, Pareto): report-only.
6. **G1 + I6a** (request → plan router, prompt-only tasks): the biggest construct-validity win.
7. **I2, I3, I4, I5, I7, I12–I14, I16** (caching, uncertainty, citations, model drift, fallback rules,
   query expansion, rerank, repacking, chunking ablation): each one is adopted only if the harness shows a
   gain.
8. **G8, G15** (holdout, live freshness): need process or secrets.
9. **G16–G19, I6b/c, I15, I18** (LLM planner, user simulator, memory, trace review, plan search, graph or
   tree RAG, propositions): experimental arms.

---

---

## 11. Where the tests live
- `tests_local/test_research_gaps_spec.py` (AI-written, not committed): §5a and §9a. Evidence tests are
  `xfail(strict=True)` and flip when a gap is closed; specification tests are skipped until their feature lands.
- `tests/` (hand-written only): five placeholder templates list the §5b and §9b use cases as `[ ]` items:
  `test_eval_reliability.py`, `test_eval_robustness_security.py`, `test_llm_cascade_and_budgets.py`,
  `test_planning_and_routing.py`, `test_rag_quality.py`.
