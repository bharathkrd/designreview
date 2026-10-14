# Architecture — how generic the agent is

*Written 2026-10-13 against branch `feat/engine-ports`. Companion to [`EXPLAINERS.md`](EXPLAINERS.md), which goes
module by module; this document answers one question: **how much of the agent is reusable for a different
domain, and what exactly would have to change?***

## The short answer

The code is split into two layers with one narrow seam between them:

| Layer | Size (Python lines) | Knows about the domain? | Changes for a new domain? |
|---|---|---|---|
| `agentkit/` — engine, transport, LLM gateway, answer audit, retrieval, run record, harness, simulator, telemetry, viewer | ≈ 7,400 | **no** (enforced by a test) | **no** |
| `packs/designreview/` — actions, plans, finding builder, claim rules, prompts, verifiers, tasks, fixtures | ≈ 2,200 (+ TOML, prompts, fixtures) | yes — all of it | replaced by `packs/<new>/` |
| `config/` — tenants, LLM routing, default pack | 3 TOML files | names the default pack and tenants | edited, not coded |

A second domain is a new folder under `packs/` plus config. Everything a run needs from the domain — what it may
call, in what order, how the answer is computed, how it is worded, and how it is graded — comes through
`Registry`, filled by the pack's `register(registry)` function.

"Generic" here is measured, not claimed. Three automated guards check it on every change (§6), including one that
writes a **brand-new pack in a temporary folder and runs it end to end with zero `agentkit` changes**.

## 1. Layers

```
                 capstone_agent.py · capstone_evals.py · rescore.py      (entry points, thin)
                                       │
┌──────────────────────────────────────┴────────────────────────────────────────────────┐
│ agentkit/  (domain-free)                                                                │
│                                                                                         │
│  registry.py ◄──────────── the only seam ───────────── packs/<name>/register(registry)  │
│                                                                                         │
│  agents/planned.py   run_plan · record_steps · answer_with_pack   (orchestration)       │
│  graph/              live DAG: verdicts, rules planner, retry policy, channels,         │
│                      eager / superstep modes, pause-for-approval, checkpoints + fork    │
│  transport/          MCP JSON-RPC client · REST reader · tool journal · catalogue ·     │
│                      safe reads · wire seam (offline guard)                             │
│  llm/                multi-provider gateway (routing.toml) · cache · rate limits ·      │
│                      cost ledger · reasoning-text filter                                │
│  answer/             narrator (fenced data, one rewrite) · claim audit · template       │
│  retrieval/          topic chunker · BM25 index · parent/child index                    │
│  record/             crash-safe TaskRun · atomic writes · JSONL logs                    │
│  harness/            tasks · ground truth · checks · grade · mutants · replay · batch   │
│  sim/                captured platform fixtures · offline replay · fault injection      │
│  telemetry/          run tree (task → node → tool / llm) · metrics · exporter           │
│  viewer/             read-only browser page over run folders                            │
│  config.py · clock.py                                                                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                       │
                         MCP tools / REST of the target platform
```

Dependencies only point downwards: `packs/` imports `agentkit/`; `agentkit/` never imports `packs/`, `core/`,
`as_client/` or an entry script. The pack is found at run time by name (`load_pack("packs.designreview")`), from
the task file's `pack = ...` or `config/project.toml`'s `default_pack`.

## 2. The seam: what a pack provides

`agentkit/registry.py` is the whole contract. A pack is a Python module with `register(registry)`:

| Slot | Kind | Required? | Used by | Design-review example |
|---|---|---|---|---|
| `@registry.action(name, writes=, retry=, preview=)` | function `(env, args, results) -> NodeResult \| value` | yes (≥ 1) | graph engine — the **allowlist**: a plan or planner can only name these | `load_design_file`, `list_revisions`, `raise_handoffs` (write, preview-only) |
| `extras["plans_dir"]` | folder of plan TOML | yes | `run_one` | `plans/rev_diff_dfm.toml` |
| `extras["tasks_dir"]` | folder of task TOML | for batches | `batch` | `tasks/t01…t09` |
| `extras["finding_builder"]` | `(results, params, run_id=, dry_run=) -> dict` | yes | `answer_with_pack` | revision delta, release gate, DFM signals — computed in code |
| `extras["claim_rules"]` | `ClaimRules` (units, required facts, banned phrases, `explain`) | yes | claim audit | "mm", "no geometry comparison" |
| `extras["template"]` | `finding -> str` | yes | fallback answer when the LLM is absent or fails the audit | `plain_rendering` |
| `extras["system_prompt"]`, `["narration_instructions"]` | text | no | narrator | `prompts/*.md` |
| `declare_read_only(tools)` | tool names | no | journal (read vs write) | computed endpoints |
| `extras["required_tools"]` | tool names | no | catalogue preflight | the seat tools the actions call |
| `@registry.probe(name)` | `(reader, arg) -> observation` | for grading | ground truth (own login, before + after) | `design_file`, `release_gate` |
| `@registry.check(name, observes=)` | pure `(bundle, params) -> [CheckOutcome]` | for grading | grader | `revision_delta_matches_db` |
| `@registry.mutant(name, target)` | `bundle -> bundle \| None` | for calibration | `mutants` — proves each check can fail | 29 faults |
| `@registry.replay_fault(name, node, target)` | `NodeResult -> NodeResult \| None` | for calibration | `replay` — end-to-end self-test | `gate_reports_ready` |
| `extras["fixtures_dir"]` | captured platform | for offline runs | `sim` | `fixtures/suryodaya.json` |

Plans, rules and tasks are **data** (TOML validated by pydantic), not code:

```toml
# a plan: first nodes + rules that may add nodes when a node finishes
name = "rev_diff_dfm"
[[nodes]]
id = "design_file"
action = "load_design_file"          # must be a registered action
args = { file_id = "{file_id}" }     # filled from the task's params
[[nodes]]
id = "revisions"
action = "list_revisions"
after = ["design_file"]
[[rules]]
name = "failed_checklists_when_gate_blocked"
[rules.when]
node = "release_gate"
nonempty = ["result.blockers"]
[[rules.add]]
id = "failed_checklists"
action = "list_failed_checklists"
after = ["release_gate"]
```

```toml
# a task: question + plan + params + the verifiers that grade it
id = "t01_battery_tray_rev_diff"
pack = "packs.designreview"
plan = "rev_diff_dfm"
prompt = "What changed between rev B and rev C ...?"
params = { file_id = "39b6…" }
[[verifiers]]
name = "release_gate_matches_db"
params = { file_id = "39b6…" }
```

## 3. One run, end to end (who does what)

| # | Step | Generic code | Pack-supplied |
|---|---|---|---|
| 1 | Write `taskrun.json` as `running`, empty `tool_journal.jsonl` | `record/`, `harness/run_one.py` | — |
| 2 | Load the pack; connect; fingerprint the tool catalogue | `registry.load_pack`, `transport/` | `required_tools` |
| 3 | Load the plan, fill placeholders, validate actions | `graph/plan_loader.py` | plan TOML, task params |
| 4 | Run the graph: ready nodes in parallel, verdicts, retries, rules add nodes, checkpoint each step, every call journaled | `graph/engine.py`, `rule_planner.py`, `transport/journal.py` | action functions, rules |
| 5 | Compute the finding from node results | `agents/planned.py` | `finding_builder` |
| 6 | Word it: LLM via gateway, data fenced as untrusted, audit every number and required fact, one grounded rewrite, else template | `answer/`, `llm/` | `claim_rules`, prompts, `template` |
| 7 | Save the record, ledger, telemetry | `record/`, `telemetry/` | — |
| 8 | Grade (separate process, files only): ground truth before/after with its own login, checks, score | `harness/` | probes, checks |
| 9 | Prove the grader: mutants on saved runs; replay faults re-run the graph | `harness/mutants.py`, `replay.py` | mutants, replay faults |

The pack never sees threads, retries, checkpoints, journals, LLM providers, caching or scoring arithmetic; the
engine never sees a file id, a revision letter or the word "release".

## 4. The generic seams, and their interfaces

Each extension point is a small interface, so a new domain *or* a new platform plugs in without editing `agentkit`.

| Seam | Interface (duck-typed / `Protocol`) | Implementations today | To support something new |
|---|---|---|---|
| Tool client | `invoke_tool(name, args) -> payload`, `offers(name) -> bool` (+ optional `catalog()`) | `SeatRpcClient` (MCP over HTTP), `SimPlatform` (fixtures), test fakes | any object with those two methods |
| Planner | `Planner.on_outcome(store, spec) -> GraphPatch \| None` (`graph/engine.py`) | `RulePlanner` (rules from plan TOML) | another class — e.g. one that asks an LLM — whose patches are still checked against the action allowlist |
| LLM | `gateway.call_detailed(...)` with routing in `config/routing.toml` | Gemini, Groq, Cerebras, Anthropic, NVIDIA, OpenRouter, Ollama (+ any OpenAI-compatible endpoint via `OPENAI_BASE_URL`) | one adapter line in `llm/gateway.py` (most reuse the OpenAI-compatible HTTP adapter) and a `[[providers]]` entry; tiers and fallback order are TOML |
| State between nodes | `NodeResult(writes=...)` + channels declared in the plan | `last_value`, `topic`, `reducer`, `ephemeral`, `barrier` | a new `Channel` subclass |
| Retry | `RetryPolicy(retry_on=...)` per action | FLAKY transport failure by default | a predicate or exception types |
| Checkpoints | `CheckpointSaver` (`put`, `get`, `list`) | `graph.json` (latest), `MemorySaver`, `JsonlSaver` | e.g. a database saver |
| Retrieval | `EvidenceIndex`, `ParentChildIndex` with a pluggable splitter | BM25 + verbatim-suffix chunking | another splitter or index behind the same calls |
| Telemetry | handler hooks `on_{chain,tool,llm,retriever}_{start,end,error}` | `Tracer` → `telemetry.json` | another handler (e.g. an exporter) |
| Grading | probes + pure checks over a saved run folder | 13 design-review checks + 3 generic ones (`run_completed`, `tool_calls_policy`, `answer_present`) | the pack's own checks |

## 5. Properties every pack gets for free

These hold for any domain because they live in `agentkit`, not in the pack:

- **Allowlisted actions.** Neither a plan, a rule nor a future LLM planner can reach a tool the pack did not
  expose as an action. Write actions never run in a dry run (the engine records their `preview`), can be paused
  for a person's approval (`--require-approval`), and are never retried.
- **Refusal is a result.** A missing record or an absent tool ends the node `declined`; downstream nodes are
  `bypassed` with the reason; the run still finishes with an honest answer.
- **Facts in code, words by the LLM.** The LLM only phrases a finding that code computed. Every number and required
  fact it writes is audited against the finding; a bad draft gets one rewrite naming the verified value, then the
  deterministic template.
- **Evidence before judgement.** The run record exists before work starts; the journal, graph checkpoint and
  ground truth are on disk before any check reads them; checks are pure functions and never touch the network.
- **Graders that are proven able to fail.** Mutants (edit a saved run) and replay faults (re-run the graph from a
  wrong node result) must each be caught by their target check, or calibration fails.
- **Offline and reproducible.** The simulator replays a captured platform with its clock frozen to the capture
  time; `AGENTKIT_OFFLINE=1` makes any real network call an error; repeated runs grade byte-identically
  (`grade --check`); CI runs all of this on Ubuntu and Windows.
- **Observable.** Every run writes a run tree (task → node → tool / LLM spans with timings, tokens, retries),
  shown in `report.md` and the viewer, never used in a score.
- **Resumable.** A crashed run restarts from `graph.json`; a paused run resumes in the same folder; any checkpoint
  can be forked with a different node result.

## 6. How genericity is enforced

`tests_local/test_modularity_guard.py` (the AI-written local suite, run before every commit; `tests_local/` is not
submitted, so CI does not run it):

1. **No domain words in `agentkit/`.** A list of design-review terms (entity names, tool names, ids, tenant names,
   "release gate", "revision", …) must not appear in any `agentkit/` file.
2. **Layering.** `agentkit/` imports nothing from `packs/`, `core/`, `as_client/` or the entry scripts; packs do
   not import the legacy `core/` or `as_client/`.
3. **No agent framework or telemetry SDK** in imports, `requirements.txt` or the CI workflow.
4. **A second pack runs unchanged.** The test writes a 30-line "widget" pack — one action, one plan, one task — into
   a temporary folder and runs it through `run_task`. It must end `done`, call exactly the one tool, and produce a
   templated answer, with no change to `agentkit`.

The whole demo pack:

```python
def register(reg):
    reg.name = "demo"

    @reg.action("echo_record", description="Widget.get for one record.")
    def echo_record(env, args, results):
        return env.client.invoke_tool("Widget.get", {"id": args["record_id"]})

    def build(results, params, *, run_id="", dry_run=True):
        r = results.get("read")
        return {"outcome": "answered" if r and r.data else "declined", "widget": r and r.data}

    reg.extras.update(plans_dir=HERE / "plans", tasks_dir=HERE / "tasks", finding_builder=build,
                      claim_rules=ClaimRules(),
                      template=lambda f: "Widget: " + str((f.get("widget") or {}).get("name")))
```

## 7. Adding a domain, step by step

1. `packs/<name>/__init__.py` with `register(reg)`; actions that call the platform's tools through `env.client`.
2. `plans/*.toml`: first nodes and follow-up rules; `tasks/*.toml`: question, plan, params, verifiers.
3. `finding_builder`, `ClaimRules`, a `template`, and (optionally) prompts.
4. For grading: probes (ground-truth reads), checks, mutants, replay faults.
5. For offline runs: `python -m agentkit.sim.capture` to record fixtures from the live platform (read-only).
6. `config/project.toml` `default_pack`, `config/tenants.toml` logins.
7. Run `python -m agentkit.harness.batch --pack packs.<name> --sim packs/<name>/fixtures --grade`, then
   `python -m agentkit.harness.mutants` and `python -m agentkit.harness.replay --calibrate`.

## 8. What is *not* generic (honest limits)

| Limit | Where | Why it is so | What a change would take |
|---|---|---|---|
| Login is the AgentSwitch seat flow (per-tenant credentials → bearer token, re-login on 401) | `transport/seat_rpc.py` `SeatSession`, `config/tenants.toml` | the only platform in scope | a different session class; the client interface (`invoke_tool`, `offers`) stays |
| Ground truth reads a REST API by entity name | `transport/rest_reader.py`, `harness/ground_truth.py` | graders must not share the agent's MCP path | another reader passed to the pack's probes |
| The planner is rule-based; the LLM never chooses tools | `graph/rule_planner.py` | answers must be reproducible and gradable offline | a `Planner` that asks an LLM is possible; its patches are still validated against the allowlist |
| No token streaming; synchronous threads, not `asyncio` | `llm/gateway.py`, `graph/engine.py` | runs are short batch jobs; the answer is audited as a whole | a streaming gateway would have to audit after completion anyway |
| One process per run, local files as storage | `harness/batch.py`, `record/` | crash isolation, files graders can read | a database `CheckpointSaver` and a run store |
| Retrieval is lexical (BM25) | `retrieval/` | small corpora; offline; explainable scores | an embedding index behind `recall`/`recall_parents` |
| Legacy `core/` and `as_client/` still ship | top level | kept as compatibility shims this release | removal is planned; nothing in `agentkit/` uses them |

## 9. Design principles in one place

1. **The framework names no domain**; the pack names nothing about threads, retries, storage or scoring.
2. **Data over code** for plans, rules, tasks, routing and tenants — validated at load time, so mistakes fail early.
3. **The LLM is the least trusted component**: it words, it does not decide; its output is audited; platform text
   given to it is fenced as data.
4. **Every outcome is a verdict**, including refusals and hand-offs; nothing is "success or exception".
5. **Evidence is written before it is judged**, by a separate process, against independently read ground truth.
6. **The test of a grader is that it fails** when the agent is wrong.
7. **Dependencies are few**: `agentkit` needs only `httpx`, `pydantic`, `python-dotenv` (and `pytest` for tests);
   every LLM provider is called over HTTP, not through an SDK. Orchestration, retrieval, tracing and evaluation are
   plain Python in this repository. (`requests`, `openai` and `networkx` remain only for the legacy `core/` engine
   and the official `harness/runner.py`.)

Several engine features (run modes, shared channels, pause/resume, checkpoint history and fork, the retry policy,
parent/child retrieval and the run tree) are adapted from external open-source designs referred to from outside
sources; each is rewritten here in plain Python with nothing imported or required.
