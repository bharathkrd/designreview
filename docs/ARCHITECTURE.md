# Architecture — how generic the agent is

*First written 2026-10-13. Updated 2026-10-14 for the research-gap batches 3 to 6 and the LLM provider changes.
Written in ASD-STE100 (Simplified Technical English) style.*

[`EXPLAINERS.md`](EXPLAINERS.md) explains each module. This document answers one question: **how much of the
agent can a different domain use again, and what must change?**

## The short answer

The code has two layers, with one narrow seam between them:

| Layer | Size (Python lines) | Knows the domain? | Changes for a new domain? |
|---|---|---|---|
| `agentkit/`: engine, router, transport, LLM gateway, answer audit, retrieval, run record, harness, simulator, telemetry, viewer | about 8,400 | **no** (a test enforces this) | **no** |
| `packs/designreview/`: actions, plans, routes, finding builder, claim rules, prompts, verifiers, tasks, fixtures | about 2,450 (and TOML, prompts, fixtures) | yes, all of it | a new `packs/<new>/` replaces it |
| `config/`: tenants, LLM routing, project defaults | 3 TOML files | names the default pack and tenants | you edit it; you do not write code |

A second domain is a new folder under `packs/`, and some configuration. A run gets all domain data through
`Registry`:

- what it can call, and in which sequence;
- how it calculates the answer;
- how it writes the answer as text;
- how the harness grades it.

The `register(registry)` function of the pack fills the `Registry`.

"Generic" here is a measurement, not a claim. Automated guards examine it on each change (§6). One guard
writes a **new pack in a temporary folder and runs it end to end, with no change to `agentkit`**.

## 1. Layers

```
                 capstone_agent.py · capstone_evals.py · rescore.py      (entry points, thin)
                                       │
┌──────────────────────────────────────┴────────────────────────────────────────────────┐
│ agentkit/  (domain-free)                                                                │
│                                                                                         │
│  registry.py ◄──────────── the only seam ───────────── packs/<name>/register(registry)  │
│                                                                                         │
│  agents/             planned.py: run_plan · record_steps · answer_with_pack             │
│                      router.py: question → plan + params (rules + pack resolver)        │
│  graph/              live DAG: verdicts, rules planner, retry policy, action timeouts,  │
│                      channels, eager / superstep modes, approval pause, checkpoints     │
│  transport/          MCP JSON-RPC client · REST reader · tool journal + argument check ·│
│                      catalogue · safe reads (partial-list flag) · wire seam (offline)   │
│  llm/                multi-provider gateway (routing.toml) · tiers · cache · rate       │
│                      limits · cost ledger · reasoning-text filter · model check         │
│  answer/             narrator (fenced data, audit-gated cascade, cost limit) · claim    │
│                      audit · quarantine of instruction-like text · template             │
│  retrieval/          topic chunker · BM25 · parent/child index · quality metrics · gate │
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

- **Dependencies point down only.** `packs/` imports `agentkit/`. `agentkit/` never imports `packs/`, `core/`,
  `as_client/` or an entry script.
- **The pack loads by name at run time:** `load_pack("packs.designreview")`. The name comes from
  `pack = ...` in the task file, or from `default_pack` in `config/project.toml`.

## 2. The seam: what a pack gives

`agentkit/registry.py` is the full contract. A pack is a Python module with `register(registry)`.

| Slot | Type | Necessary? | User | Design-review example |
|---|---|---|---|---|
| `@registry.action(name, writes=, retries=, retry=, preview=, timeout_s=)` | function `(env, args, results) -> NodeResult \| value` | yes (1 or more) | graph engine. This is the **allowlist**: a plan or a planner can name only these. | `load_design_file`, `list_revisions`, `raise_handoffs` (write, preview only) |
| `extras["plans_dir"]` | folder of plan TOML files | yes | `run_one` | `plans/rev_diff_dfm.toml` |
| `extras["tasks_dir"]` | folder of task TOML files | for batches | `batch` | `tasks/t01…t12` |
| `extras["router"]` | `RuleRouter` | for routed tasks | `run_one` (`plan = "route"`) | `routes.toml` and `resolve_design_file` |
| `extras["finding_builder"]` | `(results, params, run_id=, dry_run=) -> dict` | yes | `answer_with_pack` | revision delta, release gate, DFM signals, calculated in code |
| `extras["claim_rules"]` | `ClaimRules` (units, necessary facts, contradictions, `explain`) | yes | claim audit | "mm", "no geometry comparison" |
| `extras["template"]` | `finding -> str` | yes | the answer when no LLM is available or no draft passes the audit | `plain_rendering` |
| `extras["system_prompt"]`, `["narration_instructions"]` | text | no | narrator | `prompts/*.md` |
| `extras["narration_tiers"]` | tier names | no (default: `("quality",)`) | the cascade | `("fast", "quality")` |
| `declare_read_only(tools)` | tool names | no | journal (read or write) | the calculated endpoints |
| `extras["required_tools"]` | tool names | no | catalogue preflight | the seat tools that the actions call |
| `extras["write_tools"]`, `extras["writes_to"]` | tool names; ground-truth key prefixes | for write runs | `tool_calls_policy`, `unexpected_state_change` | the escalation tools; the escalation probes |
| `@registry.probe(name)` | `(reader, arg) -> observation` | for grading | ground truth (own login, before and after) | `design_file`, `release_gate` |
| `@registry.check(name, observes=, failure_mode=)` | pure `(bundle, params) -> [CheckOutcome]` | for grading | grader | `revision_delta_matches_db` |
| `@registry.mutant(name, target)` | `bundle -> bundle \| None` | for calibration | `mutants`: shows that each check can fail | 30 faults |
| `@registry.replay_fault(name, node, target)` | `NodeResult -> NodeResult \| None` | for calibration | `replay`: end-to-end self-test | `gate_reports_ready` |
| `extras["fixtures_dir"]` | captured platform | for offline runs | `sim` | `fixtures/suryodaya.json` |

Plans, rules and tasks are **data** (TOML that pydantic validates). They are not code:

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
plan = "rev_diff_dfm"                # or plan = "route": the pack's router decides
prompt = "What changed between rev B and rev C ...?"
params = { file_id = "39b6…" }
[[verifiers]]
name = "release_gate_matches_db"
params = { file_id = "39b6…" }
```

## 3. One run, end to end (who does what)

| # | Step | Generic code | From the pack |
|---|---|---|---|
| 1 | Write `taskrun.json` as `running`, and an empty `tool_journal.jsonl`. | `record/`, `harness/run_one.py` | — |
| 2 | Load the pack. Connect. Make the fingerprint of the tool catalogue. | `registry.load_pack`, `transport/` | `required_tools` |
| 3 | For a routed task: find the plan and its parameters from the question. | `agents/router.py` | routes, resolver |
| 4 | Load the plan, fill the placeholders, validate the actions. | `graph/plan_loader.py` | plan TOML, task params |
| 5 | Run the graph: ready nodes in parallel, verdicts, retries, timeouts, rules that add nodes, a checkpoint at each step. The journal records each call, after the argument check. | `graph/engine.py`, `rule_planner.py`, `transport/journal.py` | action functions, rules |
| 6 | Calculate the finding from the node results. Instruction-like platform text goes into quarantine. | `agents/planned.py`, `answer/quarantine.py` | `finding_builder` |
| 7 | Write the finding as text. The cheap tier writes a draft, and the audit examines each number and necessary fact. A rejected draft goes to the quality tier. If no draft passes, the template gives the answer. A cost limit applies. | `answer/`, `llm/` | `claim_rules`, prompts, `template`, `narration_tiers` |
| 8 | Save the record, the ledger and the telemetry. They include the provider and model of each LLM call. | `record/`, `telemetry/` | — |
| 9 | Grade, in a separate process, from files only: ground truth before and after (own login), checks, score. | `harness/` | probes, checks |
| 10 | Prove the grader: mutants on saved runs; replay faults run the graph again. | `harness/mutants.py`, `replay.py` | mutants, replay faults |

The pack never sees threads, retries, checkpoints, journals, LLM providers, caching or score arithmetic. The
engine never sees a file id, a revision letter or the word "release".

## 4. The generic seams, and their interfaces

Each extension point is a small interface. Thus a new domain *or* a new platform connects with no change to
`agentkit`.

| Seam | Interface (duck-typed or `Protocol`) | Implementations today | For something new |
|---|---|---|---|
| Tool client | `invoke_tool(name, args) -> payload`, `offers(name) -> bool` (and optional `catalog()`) | `SeatRpcClient` (MCP on HTTP), `SimPlatform` (fixtures), test fakes | any object with those two methods |
| Router | `RuleRouter(routes, resolve)`; `route(prompt, client) -> RouteDecision` | `routes.toml` patterns and a pack resolver | new routes (data) and a new resolver function |
| Planner | `Planner.on_outcome(store, spec) -> GraphPatch \| None` (`graph/engine.py`) | `RulePlanner` (rules from the plan TOML) | another class, for example one that asks an LLM. The engine still checks its patches against the action allowlist. |
| LLM | `gateway.call_detailed(...)` with the routing in `config/routing.toml` | OpenAI GPT-6, DeepSeek, Moonshot, Gemini, Anthropic, Groq, Cerebras, NVIDIA, OpenRouter, LM Studio, Ollama | a `[[providers]]` row only: `url` for any OpenAI-compatible endpoint, or `api = "anthropic"` / `"gemini"`. No code change. Tiers and the fallback sequence are TOML. |
| State between nodes | `NodeResult(writes=...)` and channels that the plan declares | `last_value`, `topic`, `reducer`, `ephemeral`, `barrier` | a new `Channel` subclass |
| Retry | `RetryPolicy(retry_on=...)` for each action | FLAKY transport failure by default | a predicate or exception types |
| Checkpoints | `CheckpointSaver` (`put`, `get`, `list`) | `graph.json` (latest), `MemorySaver`, `JsonlSaver` | for example a database saver |
| Retrieval | `EvidenceIndex`, `ParentChildIndex` with a pluggable splitter; `gate_hits`, `expand_query` | BM25 and verbatim-suffix chunking | another splitter or index behind the same calls |
| Telemetry | handler hooks `on_{chain,tool,llm,retriever}_{start,end,error}` | `Tracer` to `telemetry.json` | another handler, for example an exporter |
| Grading | probes and pure checks on a saved run folder | 14 design-review checks and 6 generic checks (`run_completed`, `tool_calls_policy`, `answer_present`, `tool_call_budget`, `injection_resisted`, `unexpected_state_change`). Each has a failure mode. | the checks of the pack |

## 5. Properties that each pack gets with no work

These properties apply to each domain, because they are in `agentkit`, not in the pack:

- **Allowlisted actions.** A plan, a rule, the router or a future LLM planner cannot get a tool that the pack
  did not expose as an action.
- **Safe writes.** Write actions never run in a dry run: the engine records their `preview`. A person can
  approve each write first (`--require-approval`). The engine never tries a write again.
- **Validated calls.** The journal compares the arguments of each call with the input schema of the tool. A
  bad call never goes to the platform.
- **A refusal is a result.** A missing record or an absent tool ends the node as `declined`. The engine
  bypasses the dependent nodes and records the reason. The run still completes with an honest answer.
- **A question that is not clear gets a refusal, not a guess.** The router declines and names the candidates.
- **Facts in code, words from the LLM.** The LLM only writes a finding that code calculated. The audit
  compares each number and necessary fact with the finding. A rejected draft goes to a stronger tier, with the
  verified values. If that also fails, the deterministic template gives the answer.
- **Platform text is data.** The finding goes to the LLM inside a fence. Instruction-like text goes into
  quarantine before it gets to the finding.
- **Evidence before judgement.** The run record exists before the work starts. The journal, the graph
  checkpoint and the ground truth are on disk before a check reads them. Checks are pure functions and never
  use the network.
- **Graders that can fail.** A mutant changes a saved run. A replay fault runs the graph again from an
  incorrect node result. Each must make its target check fail. If not, calibration fails.
- **Offline and reproducible.** The simulator replays a captured platform, with the clock at the capture
  time. `AGENTKIT_OFFLINE=1` makes each real network call an error. Repeated runs grade to the same bytes
  (`grade --check`). CI runs all of this on Ubuntu and Windows.
- **Observable.** Each run writes a run tree: task, node, tool and LLM spans, with timings, tokens, retries,
  provider and model. `report.md` and the viewer show it. A score never uses it.
- **Resumable.** A crashed run starts again from `graph.json`. A paused run continues in the same folder. You
  can fork each checkpoint with a different node result.

## 6. How the project enforces genericity

`tests_local/test_modularity_guard.py` is in the AI-written local suite. It runs before each commit.
`tests_local/` is not part of the submission, so CI does not run it. It has four guards:

1. **No domain words in `agentkit/`.** No `agentkit/` file can have a design-review term: entity names, tool
   names, ids, tenant names, "release gate", "revision" and others.
2. **Layers.** `agentkit/` imports nothing from `packs/`, `core/`, `as_client/` or the entry scripts. Packs do
   not import the legacy `core/` or `as_client/`.
3. **No agent framework or telemetry SDK** in the imports, in `requirements.txt` or in the CI workflow.
4. **A second pack runs with no change.** The test writes a "widget" pack of 30 lines (one action, one plan,
   one task) into a temporary folder. It runs the pack through `run_task`. The run must end as `done`, call
   exactly one tool and give a templated answer. `agentkit` does not change.

CI also runs `scripts/ste_check.py` on this document and on the explainers. That script examines the
measurable ASD-STE100 writing rules.

The full demo pack:

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

## 7. How to add a domain

1. Make `packs/<name>/__init__.py` with `register(reg)`. Its actions call the tools of the platform through
   `env.client`.
2. Write `plans/*.toml` (first nodes and follow-up rules) and `tasks/*.toml` (question, plan, params,
   verifiers).
3. Write the `finding_builder`, the `ClaimRules` and a `template`. Prompts are optional.
4. For routed tasks: write `routes.toml` and a resolver, and set `extras["router"]`.
5. For grading: write probes (ground-truth reads), checks, mutants and replay faults.
6. For offline runs: run `python -m agentkit.sim.capture` to record fixtures from the live platform. This is
   read-only.
7. Set `default_pack` in `config/project.toml`, and the logins in `config/tenants.toml`.
8. Run `python -m agentkit.harness.batch --pack packs.<name> --sim packs/<name>/fixtures --grade`.
9. Run `python -m agentkit.harness.mutants` and `python -m agentkit.harness.replay --calibrate`.

## 8. What is *not* generic (limits)

| Limit | Where | Reason | What a change needs |
|---|---|---|---|
| The login is the AgentSwitch seat flow: credentials for each tenant, a bearer token, a new login on 401. | `transport/seat_rpc.py` `SeatSession`, `config/tenants.toml` | It is the only platform in scope. | A different session class. The client interface (`invoke_tool`, `offers`) stays. |
| Ground truth reads a REST API by entity name. | `transport/rest_reader.py`, `harness/ground_truth.py` | Graders must not use the MCP path of the agent. | Another reader for the probes of the pack. |
| The planner and the router are rule-based. The LLM never chooses tools. | `graph/rule_planner.py`, `agents/router.py` | Answers must be reproducible, and the harness must grade them offline. | A `Planner` that asks an LLM is possible. The engine still validates its patches against the allowlist. |
| No token streaming. Synchronous threads, not `asyncio`. | `llm/gateway.py`, `graph/engine.py` | Runs are short batch jobs. The audit examines the full answer. | A streaming gateway must also audit after the answer is complete. |
| One process for each run. Local files are the storage. | `harness/batch.py`, `record/` | Crash isolation, and files that graders can read. | A database `CheckpointSaver` and a run store. |
| Retrieval is lexical (BM25). | `retrieval/` | Small corpora, offline use, scores that you can explain. | An embedding index behind `recall` and `recall_parents`. |
| The legacy `core/` and `as_client/` are still in the release. | top level | Compatibility shims for this release. | The project plans to remove them. Nothing in `agentkit/` uses them. |

## 9. Design principles

1. **The framework names no domain.** The pack names nothing about threads, retries, storage or scoring.
2. **Data, not code,** for plans, rules, routes, tasks, LLM routing and tenants. Pydantic validates them
   when they load. Thus errors occur early.
3. **The LLM is the least trusted component.** It writes the words. It does not decide. The audit examines
   its output. Platform text that it gets is in a data fence.
4. **Each outcome is a verdict.** This includes refusals and hand-offs. Nothing is only "success or
   exception".
5. **Evidence goes to disk before the judgement.** A separate process does the judgement, against ground
   truth that it reads itself.
6. **A grader must fail when the agent is wrong.** That is the test of a grader.
7. **There are few dependencies.** `agentkit` needs only `httpx`, `pydantic` and `python-dotenv` (and `pytest`
   for tests). The gateway calls each LLM provider over HTTP, not through an SDK. The orchestration, retrieval,
   tracing and evaluation are plain Python in this repository. Only the legacy `core/` engine and the
   official `harness/runner.py` still use `requests`, `openai` and `networkx`.

Some engine features come from external open-source designs. These are the run modes, shared channels,
pause and resume, checkpoint history and fork, the retry policy, parent and child retrieval, and the run tree. This repository
has a new implementation of each, in plain Python. It does not import or need those designs.
