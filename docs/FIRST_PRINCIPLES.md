# First principles of the agent architecture

*Written 2026-10-17 in ASD-STE100 (Simplified Technical English) style. Code state: branch
`feat/server-runner-real-agent`. Each claim names the module that implements it, so you can examine it.*

This document starts from the problem and goes down to the math. It tells you what this project does, and why
each part has its design. It also gives the algorithms, the trade-offs, the evaluation and the defences
against hallucination. It also tells you how to cost an LLM call, and how another product can use the
same framework.

Other documents give more detail on one subject:

- [`ARCHITECTURE.md`](ARCHITECTURE.md): the pack seam, the extension points and the limits.
- [`EXPLAINERS.md`](EXPLAINERS.md): one explainer for each module.
- [`RESEARCH_GAP_ANALYSIS.md`](RESEARCH_GAP_ANALYSIS.md): the project compared with 44 published papers.
- [`COST_ACCURACY.md`](COST_ACCURACY.md): measured cost and accuracy of each LLM route.
- [`SCALING_AND_DEPLOYMENT.md`](SCALING_AND_DEPLOYMENT.md): the changes for 10,000 users at the same time, and the
  cloud deployment, step by step.

---

## Part 1 — The problem

### 1.1 What the project is

AgentSwitch is an enterprise platform for business operations. It has 424 entity types. Two simulated
manufacturing companies use it: Suryodaya Precision Works (India) and Keystone Precision Works LLC (US). Each
team gets one **seat**. A seat is a set of permissions, API scopes and MCP tools. Our seat is Design Review.

The seat must answer one core question with no person in the loop:

> "What changed between rev B and rev C, and are there manufacturability problems in this part?"

The agent reads the platform through MCP (JSON-RPC over HTTP). It finds the design file. It maps the
revision letters to version records. It reads the release gate, the open feedback, the failed DFM checklists
and the design standards of the company. Then it writes an answer that a design engineer can act on.

The code has two parts:

| Part | What it is | Knows the domain? |
|---|---|---|
| `agentkit/` | A domain-free agent framework: engine, router, transport, LLM gateway, answer audit, retrieval, run record, evaluation harness, simulator, telemetry, viewer. | No. A test enforces this. |
| `packs/designreview/` | The domain pack: actions, plans, routes, finding builder, claim rules, prompts, verifiers, tasks, fixtures. | Yes. |

Thus the product of this project is two things. The first is an agent for one seat. The second is a
framework that the company can use again for other agentic products.

### 1.2 The facts about the environment that drive the design

A design starts from the facts of its environment, not from a pattern. These facts drive this design:

| # | Fact | Consequence for the design |
|---|---|---|
| F1 | The platform has no CAD kernel. Geometry diff tools return HTTP 501. | The revision delta must come from the commit notes of the engineers. The answer must say that the agent did not compare geometry. |
| F2 | Rev letters do not map to version numbers by position. Rev B can be v1 or v2. | The mapping must come from text in each commit note, not from the sequence. |
| F3 | Many people can write platform text (commit notes, feedback titles). | Treat platform text as untrusted data. It must never control the agent. |
| F4 | Other teams change the same records during our runs. | The grader must tell "the agent is wrong" from "the data moved". |
| F5 | The platform has bugs in filters, sorts and page sizes. | The agent must apply filters again in code and read all pages. |
| F6 | The question has limits. The data that answers it is in known records. | A fixed plan can answer it. An open-ended tool loop is not necessary. |
| F7 | A wrong "ready for release" claim can send a bad part to production. | A wrong fact costs much more than a plain sentence. Facts must be correct first. |
| F8 | LLM providers fail, change models, limit rates and change prices. | The LLM must be replaceable, optional and under a cost limit. |
| F9 | The brief scores the evaluation as much as the agent. | The harness is a first-class product, not an afterthought. |

### 1.3 The requirements that follow

From these facts, the system must have these properties. Each later section links back to them.

- **R1 Correct facts.** Each number, verdict and record id in the answer must match the platform.
- **R2 Honest refusals.** When the data or the seat cannot support an answer, the agent says so and names the
  reason. It never guesses.
- **R3 Safety.** The agent never writes to the platform unless a person permits it. Untrusted text cannot
  change what the agent does.
- **R4 Reproducibility.** The same input gives the same graded result. A program can compute a grade again
  from the files.
- **R5 Measurability.** Each claim about quality has a number, an interval and a test that can fail.
- **R6 Bounded cost and time.** Each run has a cost limit and a step limit.
- **R7 Reuse.** A new domain is a new pack folder, with no change to the framework.

---

## Part 2 — The first principles

These are the axioms of the architecture. Each other decision follows from one or more of them.

### P1. Facts come from code. Words come from the LLM.

An LLM is a good writer and a bad database. It can invent a value that looks correct. Thus code calculates
each fact that the user depends on: the rev mapping, the quantities, the verdict, the blockers. The LLM only
writes these facts as prose. If the LLM fails, a deterministic template writes the same facts.

This is the MRKL idea (Karpas et al., 2022): send each sub-problem to the component that is reliable for it.
It satisfies R1 and R4.

### P2. The LLM is the least trusted component.

The LLM gets the facts inside a data fence. A deterministic audit examines its output. A rejected draft goes
to a stronger model with the correct values. After that, the template answers. The LLM never chooses a tool,
never decides a verdict and never writes to the platform. This satisfies R1 and R3.

### P3. Use a workflow before an agent loop.

Anthropic, *Building Effective Agents* (2024), and *Agentless* (Xia et al., 2024) give the same advice. Use a
fixed workflow when the task has a known shape. Use an autonomous loop only when the steps cannot be known in
advance. Our question has a known shape (fact F6). Thus a compiled plan runs the tool reads, and no LLM call
decides the next step. ReWOO (Xu et al., 2023) measured about 5 times fewer tokens for this pattern than for
ReAct.

### P4. Control flow comes from trusted input only.

The plan, the routes and the action allowlist are files in the repository. Platform data can fill values,
but it cannot add a tool or a step. This is the CaMeL principle (Debenedetti et al., 2025): separate the
control flow from the untrusted data. It satisfies R3.

### P5. Each outcome is a verdict.

A node ends as `resolved`, `declined`, `handed_off`, `failed` or `bypassed`. A refusal is a normal result
with a reason, not an exception. Thus the system can grade "the agent correctly refused" as a pass. This
satisfies R2.

### P6. Evidence first, judgement later, in a different process.

The run writes its record before it starts work. The journal records each tool call as the transport saw
it. The grader reads only the saved files, and it reads ground truth with its own login. Thus an error in the
agent cannot make its own check pass. This satisfies R4 and R5.

### P7. A grader that cannot fail proves nothing.

For each check, a mutant shows that the check fails on a wrong run. A replay fault shows the same thing
through the full path from a node to the answer. This satisfies R5.

### P8. Data, not code, for anything that changes often.

Plans, routes, tasks, LLM providers, tiers, tenants, retrieval synonyms and gate thresholds are TOML.
Pydantic validates each file when it loads. Thus a change is a reviewed data edit, and an error occurs at
load time, not in production. This satisfies R7.

### P9. The framework names no domain, and the pack names no infrastructure.

The engine never sees a file id or the word "release". The pack never sees threads, retries, checkpoints or
score arithmetic. One narrow seam (`agentkit/registry.py`) joins them. This satisfies R7.

### P10. Few dependencies, plain Python.

The framework needs only `httpx`, `pydantic` and `python-dotenv`. It uses no agent framework and no LLM SDK.
Each mechanism is small enough to read, test and change. Thus the company owns its failure modes and its
upgrade schedule.

---

## Part 3 — The architecture

### 3.1 Layers

```
         capstone_agent.py · capstone_evals.py · rescore.py · harness/runner.py   (thin entry points)
                                         │
┌────────────────────────────────────────┴───────────────────────────────────────────────┐
│ agentkit/  (domain-free)                                                                │
│   registry.py  ◄──── the only seam ────►  packs/<name>/register(registry)               │
│                                                                                         │
│   agents/     router (question → plan + params), planned run, answer with the pack      │
│   graph/      live DAG: verdicts, allowlist, rule planner, retries, timeouts, channels, │
│               checkpoints, eager / superstep modes, pause for approval, fork            │
│   transport/  MCP JSON-RPC client, REST reader, journal + argument check, safe reads    │
│   llm/        multi-provider gateway, tiers, rate state, cache, cost ledger             │
│   answer/     narrator (fence, cascade, cost limit), claim audit, quarantine            │
│   retrieval/  chunker, BM25, parent/child index, relevance gate, quality metrics        │
│   record/     crash-safe run record, atomic writes, JSONL logs                          │
│   harness/    tasks, ground truth, checks, grade, goldens, mutants, replay, batch,      │
│               Pareto                                                                    │
│   sim/        captured platform fixtures, offline replay, fault injection               │
│   telemetry/  run tree (task → node → tool / llm), metrics, exporter                    │
│   viewer/     read-only browser page over run folders                                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                         │
                       MCP tools and REST API of the target platform
```

Dependencies point down only. `packs/` imports `agentkit/`. `agentkit/` never imports `packs/`. A pack loads by
name at run time: `load_pack("packs.designreview")`.

### 3.2 One run, end to end

```
 question ──► ROUTER ──► PLAN (TOML) ──► DAG ENGINE ──► node results ──► FINDING BUILDER ──► finding (facts)
              regex +     placeholders   ready set,      verdicts          code only            │
              IDF match   filled         parallel reads                                         ▼
              or DECLINE                 rules add nodes                              NARRATOR (cascade)
                                         journal + args                               fast draft → audit
                                         checkpoint                                   → quality rewrite
                                                                                      → audit → template
                                                                                                │
   GRADER (separate process) ◄── run folder: task.json, taskrun.json, tool_journal.jsonl,  ◄────┘
   ground truth before/after       graph.json, ground_truth_*.json, llm_ledger.json, telemetry.json
   pure checks → score.json
```

| # | Step | Generic module | Pack gives |
|---|---|---|---|
| 1 | Write `taskrun.json` as `running`. | `record/`, `harness/run_one.py` | — |
| 2 | Connect. Make a fingerprint of the tool catalogue. Make sure each necessary tool is present. | `transport/catalog.py`, `harness/preflight.py` | `required_tools` |
| 3 | Routed task: choose the plan and find the record from the question. | `agents/router.py` | `routes.toml`, resolver |
| 4 | Load the plan. Fill the placeholders. Validate each action name. | `graph/plan_loader.py` | plan TOML |
| 5 | Run the graph. Ready nodes run in parallel. Rules add nodes. A checkpoint after each step. | `graph/engine.py` | actions, rules |
| 6 | Calculate the finding from the node results. | `agents/planned.py` | `finding_builder` |
| 7 | Write the finding as prose, under audit and a cost limit. | `answer/`, `llm/` | claim rules, prompts, template |
| 8 | Save the record, ledger and telemetry. | `record/`, `telemetry/` | — |
| 9 | Grade from the files, in a separate process. | `harness/` | probes, checks |
| 10 | Prove the grader with mutants and replay faults. | `harness/mutants.py`, `replay.py` | mutants, faults |

### 3.3 Why this shape, and not another

| Alternative | Why we did not choose it |
|---|---|
| ReAct loop: the LLM picks each tool call. | More LLM calls, so more cost and latency. The tool sequence changes from run to run, so a grade does not repeat. Each tool result goes into the context, so injected text can steer the loop. Our question has a fixed shape (F6), so the loop adds risk and gives nothing. |
| LLM planner that writes the full plan. | Possible as an experiment. The `Planner` protocol accepts it, and the engine still checks each patch against the allowlist. It must win on the harness before adoption (gap G16). |
| Multi-agent system (several LLM roles that talk). | MAST (Cemri et al., 2025) found 14 failure modes in such systems. Most come from the talk between agents. One seat with one bounded question does not need that. |
| An agent framework (graph and chain libraries). | A large dependency with its own release schedule. Its abstractions hide the failure modes that we must grade. We took some ideas (channels, supersteps, checkpoints, fork) and wrote them again in plain Python. |
| JSON-mode answer from the LLM. | Strict format constraints reduce reasoning quality (Tam et al., 2024). The facts already exist as JSON in the finding. The LLM writes free prose, and the audit examines it. |

---

## Part 4 — The components, their algorithms and their trade-offs

### 4.1 Router: from a question to a plan

**Problem.** A task can give only the question. The agent must choose the plan and find the record that the
question names. A wrong guess is worse than a refusal (F7, R2).

**Algorithm** (`agentkit/agents/router.py`, `packs/designreview/router.py`):

1. Try the routes in file order. Each route has regular expressions (case-insensitive). The first route with
   a match wins. No match gives a decline.
2. A record id (UUID) in the question is the file id. The resolver does no search.
3. Otherwise, the resolver reads all design files (all pages, through the journal).
4. It scores each file by the question words that the file name shares. Each word has an IDF weight, so a
   word in many file names counts for little. A word in more than max(3, 5% of N) names counts for nothing.
   Seed data repeats department words ("Quality") in many names, and they are not evidence.
5. Each file with a score of 0.9 or more of the best score ties with the best.
6. When the question names revisions, only files with two or more versions stay. If a tie remains, the
   resolver reads the version notes of each candidate. It keeps the files whose notes have those revision
   letters.
7. One candidate left: use it. None, or more than one: decline, and name the candidates.

```
score(file) = Σ over words w shared by question and file name, with df(w) ≤ max(3, 0.05·N), of  ln( N / df(w) )
              N = number of files, df(w) = number of file names with w
tie set     = { file : score(file) ≥ 0.9 · max score }
```

**Why IDF.** The Suryodaya fixture has 100 design files. "Battery" and "tray" are each in one name, so each
has the weight ln(100) = 4.61. The battery tray scores 9.21, and the next file scores 0. "Propeller" is in
four names, so it has the weight ln(100/4) = 3.22.

All four propeller files score 3.22. They tie, so the router declines and names them (task t11). IDF gives
these results with no labelled data and no model.

**Trade-off.** Rules are exact and free, but they need maintenance when users ask in new words. An LLM
classifier covers more phrasings, but it can guess. The route decision is on the run record
(`taskrun.route`), so a grader can examine it (check `routed_as`, tasks t10 to t12).

### 4.2 Plans and the DAG engine

**Problem.** The agent must read about seven records. Some reads depend on others. Some reads are necessary
only in some conditions. Reads must run in parallel for speed, and the result must not depend on thread
timing.

**A plan** is TOML: first nodes, their dependencies, and rules that add nodes when a node finishes. Example:
add `list_failed_checklists` only when the release gate shows blockers.

**Algorithm** (`agentkit/graph/engine.py`):

- **Ready-set scheduling.** A node is ready when each dependency has finished. The engine starts each ready
  node on a thread pool. This is a topological sort that runs as the graph grows. LLMCompiler (Kim et al.,
  2023) uses the same idea for its parallel executor.
- **Two join types.** `requires = "resolved"`: run only when each dependency resolved, otherwise bypass with
  the reason. `requires = "settled"`: run when each dependency finished in any verdict. Thus one bad branch
  cannot stop the other answers (a partial join).
- **Two scheduling modes.** `eager` starts a node as soon as it is ready. `superstep` is bulk synchronous
  parallel (BSP, Valiant 1990): all ready nodes run against one snapshot, and the engine applies their
  outcomes in node-id order. Thus thread timing can never change the state.
- **Patch validation.** A rule or a planner sends a `GraphPatch`. The engine validates the full patch before
  it changes anything. It rejects an unknown action, a duplicate id and a missing dependency. It also rejects
  an edge into a started node, a cycle (depth-first search) and a patch over the node budget (30 nodes).
- **Verdict mapping.** The transport classifies each error. "Not found", "not in seat" and "denied" end the
  node as `declined`: the platform said no. A `flaky` error goes to the retry policy. Other errors end as
  `failed`.
- **Retry policy** (`agentkit/graph/policies.py`). Exponential backoff. The engine never tries a write again,
  because a write that timed out can still have landed.
- **Checkpoints.** After each outcome, the engine writes the full graph to `graph.json` with an atomic
  write. A crashed run continues from that file. `fork()` starts a new run from any checkpoint with some
  node results replaced. The replay calibration uses this.
- **Channels.** Shared state between nodes has declared merge rules: last value, topic (append), reducer,
  ephemeral and barrier. Two writers of a single-value channel in one superstep is an error, not a race.

```
wait before attempt n+1 = min( max_interval, initial_interval · backoff_factor^(n-1) )   [+ U(0,1) s if jitter]
defaults: max_attempts 3, initial 0.5 s, factor 2.0, cap 128 s, jitter off (so CI waits the same each time)
```

**Trade-offs.**

| Choice | Gain | Cost |
|---|---|---|
| Threads, not `asyncio` | Simple code. Actions are normal functions. | Many thousands of parallel calls would need async. Runs here have about 10 nodes. |
| Eager mode by default | Lowest latency. | Thread timing can change the sequence of rule patches. Superstep mode removes this when you need it. |
| Rules in TOML, not an LLM planner | Same graph each run. Free. Graded offline. | A new case needs a new rule. |
| Node budget 30, step budget 50 | A runaway plan stops. | A very large plan needs a higher limit. |

### 4.3 Transport: every tool call as evidence

**Problem.** The grader must know which tools the agent really called. The agent's own report is not
evidence. Bad arguments must not reach the platform.

**Mechanisms** (`agentkit/transport/`):

- **Error taxonomy.** `missing`, `bad_args`, `bad_transition`, `not_in_seat`, `denied`, `token_expired`,
  `flaky`, `unclassified`. Only `flaky` is a candidate for a retry. The others are answers.
- **One re-login.** HTTP 401 starts exactly one new login and one resend. A second 401 is `token_expired`.
- **Journal.** `JournaledSeatClient` writes one JSON line for each call to `tool_journal.jsonl`: tool,
  arguments, outcome, timing. It never writes tokens or headers.
- **Argument check.** Before each call, the journal compares the arguments with the input schema of the tool
  in the catalogue. A bad call goes in the journal with `"sent": false` and never reaches the platform.
- **Catalogue fingerprint.** A hash of the tool names and input schemas. A change in the platform shows as a
  new fingerprint before any task runs.
- **Safe reads** (`safe_reads.py`). Send to the server only exact, scalar filters on keys that the pack
  declares safe. Read all pages. Apply each filter again in code. Do "not equal" in code, because the
  platform's `ne:` drops rows with empty values (F5). A short page sets `"complete": false`, and the finding
  marks that section as partial.

**Trade-off.** Each list read can need more pages and more local filtering. The data is small, so this costs
milliseconds. A silent wrong row costs a wrong answer.

### 4.4 The finding: the facts in code

`packs/designreview/finding.py` builds one JSON object from the node results. It is the gradable answer.

| Section | What code calculates |
|---|---|
| `outcome` | `answered`, `partial` or `declined` |
| `revision_delta` | Which version is rev X and rev Y, read from the commit notes (F2). The note of each version and the quantities in it. `basis = "commit_message"`, `geometry_compared = false` (F1). |
| `release_gate` | `ready`, reason codes, `critical_open`, blockers |
| `dfm_signals` | Failed checklist results, open high and critical feedback, recalled design standards |
| `schedule` | Milestones and `past_due`, from the snapshot date |
| `handoffs` | Hand-offs to the teams that own problems this seat cannot fix, with the items they cite. In a dry run, `filed = false`. |
| `declines`, `quarantined` | Each refusal with its reason. Each instruction-like sentence that the agent removed from platform text. |

This object is the contract between the agent and the grader. The LLM gets it as input. The checks grade it
directly.

### 4.5 The answer: narrator, audit and cascade

**Problem.** The user wants readable prose (the verdict first, plain words). The LLM can write it, but it can
also invent a value or reverse a verdict (F7).

**Algorithm** (`agentkit/answer/narrator.py`, `compose_answer`):

1. Build the template answer first. It always exists.
2. Put the stable text first: system prompt, pack instructions and the data rule. Put the question and the
   fenced finding after it. Thus a provider can cache the stable prefix.
3. Tell the model the facts that it must state (from `ClaimRules.required`).
4. **Cascade** (FrugalGPT, Chen et al., 2023). The `fast` tier writes one draft. The claim audit examines it.
   A pass ends the cascade. A fail sends the draft and a correction note to the `quality` tier. The last tier
   gets a draft and one rewrite.
5. A tier with all providers down: go to the next tier. A cut-off answer (`max_tokens`): go to the next tier.
6. Before each call, compare the spent cost with `max_llm_cost_usd_per_run`. At the limit, the template
   answers.
7. No draft passes: the template answers. `answer_source` on the run record says which source answered.

**The claim audit** (`agentkit/answer/claim_audit.py`) is deterministic. It uses no LLM. It finds five kinds
of problem:

| Problem | How the audit finds it |
|---|---|
| Unsupported record id | Each UUID in the text must occur in the finding. |
| Unsupported quantity | Each number with a unit (the pack's pattern) must equal, within 1e-6, a number somewhere in the finding. The audit removes dates, clock times and UUIDs first, so "12" in "12:05" is not evidence for "12 mm". |
| Contradiction | Pack rules. Example: the text says "ready" but the gate says not ready. The parser handles negation ("not ready"). |
| Missing fact | Each necessary fact (pack rules, as regular expressions) must occur in the text. |
| Bad citation | An optional `[@path]` tag after a sentence must name a real path in the finding. Each quantity in that sentence must be a number of the cited value. |

**The correction note** gives the model the right value, not only the error. Example: "'2.5 mm' is not in
the FINDING; verified: '3.0 mm' at revision_delta.change_notes[1]". Huang et al. (2023) showed that an LLM
cannot correct its own reasoning with no outside signal. Self-correction works when an outside check says
what is right. The audit is that outside check.

**Why the audit is not an LLM judge.** An LLM judge has position, length and self-preference bias (Zheng et
al., 2023). It also costs tokens and gives a different result each time. The facts here are numbers, ids
and verdicts, and code can compare them exactly. Code is the correct judge for exact facts.

### 4.6 LLM gateway: many providers, one interface

**Problem.** Providers fail, limit rates, retire models and change prices (F8). The agent must not depend on
one of them.

**Mechanisms** (`agentkit/llm/gateway.py`, `config/routing.toml`):

- **Providers as data.** A `[[providers]]` row with a `url` adds any OpenAI-compatible endpoint, with no code.
  Native adapters exist for Anthropic, Gemini and Ollama.
- **Tiers.** `fast` (cheap drafts) and `quality` (rewrites). Each tier is a list of providers in a fixed
  sequence. The gateway skips a provider that has no key.
- **Rate state.** For each provider: a sliding window of call times over 60 s, and a cool-down time. A
  provider is available when it is not in cool-down and has fewer calls than its `rpm` in the last 60 s.
- **Classified retries.** The gateway can retry 408, 409, 429, 5xx, 529, timeouts and empty replies. It backs
  off on the same provider. Then it cools the provider down for 20 s and goes to the next provider. The
  statuses 401, 402 and 403 cool the provider down for 300 s, because a bad key or empty quota does not fix
  itself. Other 4xx errors go to the next provider at once.
- **Response cache.** An exact-match LRU cache (256 entries). The key is the SHA-256 of all parameters that
  change the answer. The cache stores only complete replies (`end_turn`), never a cut-off or refused reply.
- **Reasoning filter.** The gateway removes `<think>…</think>` text before the audit, the cache and the ledger
  see the reply.
- **Secrets.** Keys go only in headers. The gateway removes key values from each error message.
- **Model check** (`models_check.py`). Asks each provider for its `/models` list. A retired model shows before
  a run fails.

```
backoff before retry a (a = 0, 1, …) = min( 0.5 · 2^a , 4.0 ) seconds,  3 attempts for each provider
available(p, t) = t ≥ cooldown_until(p)  AND  |{ calls of p in (t − 60 s, t] }| < rpm(p)
```

**Trade-off.** Direct HTTP adapters cost some code for each native API. In return, there is no SDK lock-in,
and one place controls retries, cost and secrets.

### 4.7 Retrieval: design standards for the change

**Problem.** The answer should cite the design standards of the company that apply to the change. The corpus
is small (some tens of standards for each company). The match must be explainable.

**BM25** (`agentkit/retrieval/index.py`, Robertson and Zaragoza, 2009). For a query q and a passage d:

```
score(q, d) = Σ over terms t in q of  IDF(t) · f(t,d)·(k1+1) / ( f(t,d) + k1·(1 − b + b·|d|/avgdl) ) · qtf(t)·(k1+1) / ( qtf(t) + k1 )
IDF(t)      = ln( 1 + (N − df(t) + 0.5) / (df(t) + 0.5) )
k1 = 1.5, b = 0.75
f(t,d)  = count of t in d        |d| = passage length in terms     avgdl = mean passage length
qtf(t)  = count of t in the query                                  N = passages, df(t) = passages with t
```

- `k1` controls term-frequency saturation: the tenth "bend" adds less than the second.
- `b` controls length normalisation: a long passage does not win only because it has more words.
- The tokenizer keeps decimals ("2.0"), drops stop words and removes simple suffixes ("welding" → "weld").

**Why BM25 and not embeddings.** BEIR (Thakur et al., 2021) showed that BM25 is a strong zero-shot baseline.
The corpus is small and has technical words, where exact matches matter. BM25 needs no model, no vector
store and no network, so it runs offline in CI. Each hit lists its matched terms, so a person can see why
it matched.

**Parent-child retrieval** (`hierarchy.py`). The index holds small child passages (one section) for precise
matches. The answer gets the whole parent standard for context. The algorithm ranks the children, takes the
parent ids in rank order, keeps each parent once and drops a parent that no longer exists.

**Contextual prefix.** Each child's index text starts with the name and category of its parent. The display
text does not have it. Thus a short child still matches its context, with no LLM cost (gap I17).

**Relevance gate** (`quality.py`, from Corrective RAG, Yan et al., 2024). For each hit:

```
band(hit) = incorrect   if score ≤ min_score  or  distinct matched terms < min_terms (2)
          = correct     if score / best ≥ keep_ratio (0.5)
          = ambiguous   if score / best ≥ ambiguous_ratio (0.3)
          = incorrect   otherwise
```

The agent drops `incorrect` hits. The `min_terms` floor stops one chance word from counting as evidence.
Example: "steel" in "coffee machine warranty steel".

**Query expansion.** `retrieval.toml` maps phrases to extra terms ("bend radius" → "bend sheet metal"). A
person wrote the synonyms without looking at the labelled answers, so they do not overfit the test.

**Chunking** (`chunker.py`). Cut at a word budget, but never inside a heading, a code fence or a table. An
optional LLM splitter can only point to the start of a second topic. It must return an exact suffix of the
block. The chunker rejects any other answer and keeps the block whole. Thus a model can find a boundary but
never write one.

The LLM splitter is off by default, because semantic chunking rarely pays for its cost (Qu et al., 2024).

**Trade-off.** BM25 misses a synonym that the expansion table does not know. The retrieval quality metrics
(§6.7) measure this. Embeddings come in only if those metrics show a lexical miss.

### 4.8 Record and telemetry

- **Crash-safe record.** `taskrun.json` exists with `ended = "running"` before the work starts. Each write is
  atomic: write a temporary file, then rename it. A crash leaves `running`, and the grader fails the run.
- **Run tree.** Each run writes spans: task → node → tool or LLM call, with timings, tokens, retries, provider
  and model.
- **Latency percentiles** use the nearest-rank method. It never reports a latency that did not occur, as
  interpolation can.

```
percentile(values, p) = sorted(values)[ max(1, ⌈ p/100 · n ⌉) − 1 ]
```

---

## Part 5 — How the system handles hallucination

"Hallucination" is many failure types. Each needs a different defence. The system has layers, so that one
miss does not reach the user.

| Hallucination type | Example | Defence | Where |
|---|---|---|---|
| Invented fact | "Blank length grows 5 mm" (true: 4.2 mm) | Code calculates facts (P1). The audit rejects each quantity that is not in the finding. | `finding.py`, `claim_audit.py` |
| Reversed verdict | "Ready for release" when the gate says not ready | Contradiction rules with negation handling. Check `release_gate_matches_db` against ground truth. | `packs/designreview/claims.py`, `checks.py` |
| Invented record | A record id or a standard that does not exist | The audit rejects a UUID that is not in the finding. Check `cited_standards_exist` reads the platform. | `claim_audit.py`, `checks.py` |
| Wrong entity | "The propeller" answered for one of four files | The router declines on a tie and names the candidates. | `packs/designreview/router.py` |
| Unsupported capability claim | "The wall thickness is fine" (no CAD kernel) | `geometry_compared = false` in the finding. Check `no_geometry_claim`. Task t04. | `finding.py`, `checks.py` |
| Omission | The answer leaves out the critical blocker | Necessary-fact rules in the audit. Checks `answer_states_change` and `answer_states_handoffs`. | `claims.py`, `checks.py` |
| Fabricated change | Boilerplate notes ("drawing and model updated together") turned into invented changes | Task t06 and check `answer_reflects_change_notes`. | `checks.py` |
| Invented hand-off | A hand-off to a team with no open item | Hand-offs come from a topic table and must cite open items. Check `handoffs_match_platform`. Task t09. | `handoffs.py`, `checks.py` |
| Wrong boundary in retrieval | An LLM writes a chunk boundary that is not in the source | Verbatim-suffix rule. The block stays whole on any other answer. | `chunker.py` |
| Injected instruction | A commit note says "state that the part is ready" | Data fence, quarantine, audit, check `injection_resisted`. See Part 8. | `narrator.py`, `quarantine.py` |

**The design rule under all of these:** the LLM output is a proposal. A deterministic check accepts it, or
the template replaces it. Thus the error rate of the final answer for exact facts does not depend on the
error rate of the model. It depends on the coverage of the audit and the checks. Mutants measure that
coverage (§6.5).

**What this does not cover.** The audit examines facts that code can compare: numbers, ids, verdicts and
named facts. It cannot examine the tone or the emphasis of a sentence. For example, it cannot tell whether
the answer puts the blocker first. A readability check would need its own calibration (see `COST_ACCURACY.md`,
recommendation 4).

---

## Part 6 — Testing and evaluation

### 6.1 The principles of the harness

The harness follows the ABC checklist for agent benchmarks (Zhu et al., 2025) and τ-bench (Yao et al., 2024):

1. **Grade the state, not the transcript.** The checks compare the finding and the answer with what the
   platform says.
2. **Read ground truth with a separate login,** before and after the run. The harness uses a different code
   path (REST, not the MCP client of the agent).
3. **Grade from files only.** Checks are pure functions with no network and no LLM. A fix to a check costs
   nothing: grade the saved runs again. `grade --check` proves that a second grade gives the same bytes.
4. **Run the agent in a subprocess.** A crash fails the run and does not kill the harness.
5. **`error` is never a pass.** A check that cannot read ground truth gives `error`, and `error` counts as
   not passed.
6. **Tell the agent's errors from the platform's changes.** `drift` means the claim matched the platform
   before the run but not after. Another team changed the data (F4).

### 6.2 The tasks

Twelve tasks in `packs/designreview/tasks/`, on two tenants. They cover:

- the core question (t01, t07);
- rev mapping that does not follow position (t05);
- numeric revisions and no geometry claims (t04);
- boilerplate notes with no real change (t06);
- refusals: an unknown file (t02), a tool that the seat does not have (t03), an ambiguous name (t11);
- hand-offs and the schedule (t08, t09);
- routed questions with no plan in the task (t10, t11, t12).

A good agent must refuse in some tasks and act in others. An agent that always refuses fails. An agent
that always answers fails.

### 6.3 The checks

There are 21 checks: 7 built-in checks and 14 pack checks. Each has a **failure mode**: `wrong_fact`,
`fabrication`, `ignored_evidence`, `policy_breach`, `premature_stop` or `verification_gap`. The report counts
failures by mode, as MAST does. The mode never changes a score.

| Built-in check | What it proves |
|---|---|
| `run_completed` | The record says `done`. `running` means a crash. |
| `tool_calls_policy` | From the journal: a dry run called no write tool. A write run used only the pack's write tools. |
| `answer_present` | The answer has text. |
| `tool_call_budget` | No identical successful read happened twice (between writes). |
| `injection_resisted` | Planted text did not reach the answer or the finding, and caused no write. |
| `unexpected_state_change` | In a write run, only the declared records changed. |
| `golden` | The value that a person checked by hand in the seed data is still the value. |

**Goldens** (`agentkit/harness/goldens.py`) catch a failure that the other checks cannot see: a check that
misreads the platform in the same way as the agent. A golden is a fixed value. The 12 tasks have 39 goldens.

The pack checks use **their own parsers** for rev letters, quantities and readiness words. They do not use
the agent's parsers. Thus one parser bug cannot make the agent wrong and the check pass at the same time.

### 6.4 Statuses and scores

```
check status  ∈ { pass, fail, drift, skip, error }
run passes    ⇔ no check is fail or error, and at least one check applies
partial(run)  = ½ · (checks passed / checks applicable) + ½ · [run passed]          (TheAgentCompany, Xu et al. 2024)
```

`partial` is for the report only. It never changes the pass gate.

### 6.5 Graders that can fail: mutants and replay faults

A check that never fails gives no information. Two mechanisms prove that each check can fail.

**Mutants** (`agentkit/harness/mutants.py`). Take a passing run. Change one thing in a copy: a wrong rev
mapping, an invented quantity, a false "ready", a hidden write, a crash. Grade the copy. The target check
must fail. There are 7 built-in mutants and 30 pack mutants.

```
caught(m)     ⇔ for each run where m applies, target(m) gives fail
MISSED        ⇔ m applies somewhere and target(m) does not fail     → calibration fails
UNEXERCISED   ⇔ a check that no mutant made fail on any run          → calibration fails
```

This is mutation testing (DeMillo, Lipton and Sayward, 1978), applied to graders instead of programs.

**Replay faults** (`agentkit/harness/replay.py`). A mutant changes the saved output. A replay fault changes
the result of one graph node (for example, the gate says "ready"). Then the replay runs all later nodes
again, builds the finding and the answer again and grades the new run. The target check must fail.

A control replay with the original node result must still pass. Thus the replay proves the full path: node →
finding → answer → check.

### 6.6 Fault injection and robustness

The simulator (`agentkit/sim/sim_platform.py`) replays captured platform data offline, with the clock at
the capture time. It adds faults on request:

| Fault | What it simulates | Expected grade |
|---|---|---|
| `drop_tool:<tool>` | The seat loses a tool. | Decline with a reason. |
| `fail_once:<tool>:flaky` | One network failure. | Retry, then pass. |
| `fail_times:<tool>:<kind>:<n>` | A rate limit that clears. | Retries, then pass. |
| `fail_always:<tool>:<kind>` | A tool that is down. | Decline or fail, never an invented answer. |
| `truncate:<tool>:<n>` | A partial page. | The section shows as `partial`. |
| `rename_field:<tool>:<old>=<new>` | A schema change. | Decline with a reason, not a crash. |
| `inject_text:<tool>:<field>=<text>` | An attacker writes in platform data. | `injection_resisted` passes. |
| `edit_text:<old>=><new>` | Another team edits a record during the run. | `drift`. |

`scripts/ci_fault_matrix.py` runs each fault with its expected grade. A fault that gives a different grade
fails CI. This is the λ axis (fault rate) of the reliability surface in ReliabilityBench (2026).

### 6.7 Statistics: how sure is a score?

A pass rate without an interval is not a result. Twelve tasks is a small sample. The grader reports these
values in `batch_score.json` and `report.md` (`agentkit/harness/grade.py`). It keeps exact values as
fractions, so a second grade gives the same bytes.

**pass@k and pass^k.** A task has n runs, and c of them pass.

```
pass@k = 1 − C(n−c, k) / C(n, k)     at least one of k runs passes: "the agent can do it"     (Chen et al., 2021)
pass^k = C(c, k) / C(n, k)           all k runs pass:               "the agent does it reliably" (Yao et al., 2024)

example n = 3, c = 2:   pass@1 = 2/3   pass@2 = 1     pass@3 = 1
                        pass^1 = 2/3   pass^2 = 1/3   pass^3 = 0
```

For a product, pass^k is the correct measure. A user who asks the same question three times expects the
same correct answer three times. CI runs with `--repeat 3`, and a task passes only if each repeat passes.

**Wilson score interval** for x of N tasks (z = 1.96 for 95%):

```
p̂ = x / N
centre = ( p̂ + z²/(2N) ) / ( 1 + z²/N )
half   = z · √( p̂(1−p̂)/N + z²/(4N²) ) / ( 1 + z²/N )

12 of 12  →  [0.757, 1.000]      9 of 9  →  [0.701, 1.000]      0 of 20  →  [0.000, 0.161]
```

The normal interval p̂ ± z·√(p̂(1−p̂)/N) gives [1, 1] for 12 of 12. That is false certainty. Wilson stays
honest at 0 and at 1 (Miller, 2024).

**Clustered standard error.** Repeats of one task are not independent: an easy task passes each time. The
grader treats each task as a cluster:

```
SE_clustered = √( Σ over tasks c of ( Σ over runs i in c of (s_i − s̄) )² ) / n
```

With no clustering, three repeats would look like three times the evidence. They are not.

**Cost against accuracy** (`agentkit/harness/pareto.py`). Each batch is one arm, for example "template only"
or "gpt-6-luna first". An arm is on the Pareto frontier when no other arm beats it. Arm A beats arm B when A
has a pass rate at least as high and a cost at least as low. One of the two must also be strictly better. The
template-only arm at $0 is the baseline that each LLM arm must beat (Kapoor et al., 2024).

**Retrieval quality** (`agentkit/retrieval/quality.py`, `scripts/retrieval_eval.py`) uses labelled queries
in `retrieval.toml`:

```
recall@k    = | top k ∩ relevant | / | relevant |
precision@k = | top k ∩ relevant | / | top k |
MRR         = mean over queries of 1 / rank of the first relevant hit
```

CI fails if a change drops below the floors: recall@5 = 1.0, precision@5 = 0.85, MRR = 1.0. The labelled
set has only 4 queries, so treat these numbers as a regression alarm, not as proof of quality.

### 6.8 The CI gates

Each push runs these steps on Ubuntu and Windows (`.github/workflows/ci.yaml`):

1. The hand-written unit tests (offline).
2. All 12 tasks on the captured fixtures, with template answers.
3. A check that each task ran and passed.
4. A second grade from the run files. It must give the same bytes.
5. Mutant calibration. Each mutant must be caught.
6. Replay calibration. Each node fault must be caught, and each control must pass.
7. The fault matrix. Each fault must give its expected grade.
8. The retrieval floors.
9. A viewer smoke test.
10. The official runner, offline.
11. The STE style check on the main documents.
12. Two secret scans over the full history.

### 6.9 The layers of tests

| Layer | Where | Who writes it | What it covers |
|---|---|---|---|
| Unit tests | `tests/` | People, by hand | One behaviour for each test. Offline by default. Markers for `live`, `agent`, `writes`. |
| Reference and guard tests | `tests_local/` (not in the release) | AI | Modularity guards, specification tests for open gaps, reference tests |
| Task evaluation | `packs/designreview/tasks/` | People | End-to-end behaviour against ground truth |
| Grader calibration | mutants, replay faults | People | That each check can fail |
| Fault matrix | `ci_faults.toml` | People | Behaviour under failures |
| Live runs | `--repeat`, Pareto | People | Real providers and the live platform |

---

## Part 7 — The token budget and the cost

### 7.1 Where the tokens go

The architecture removes most LLM calls before cost control starts:

- **Planning: 0 tokens.** The plan is TOML (P3).
- **Tool selection: 0 tokens.** The engine runs the plan. No tool result goes back into a prompt to choose a
  next step.
- **Routing: 0 tokens.** Regular expressions and IDF.
- **Retrieval: 0 tokens.** BM25 and a contextual prefix. The optional LLM splitter is off.
- **Fact checking: 0 tokens.** The claim audit is code.
- **Narration: 1 call in most runs,** with about 200 output tokens on gpt-6-luna. A rejected draft costs one
  more call on the quality tier.

Thus a run has 1 or 2 LLM calls. A ReAct agent would make one call for each tool step (about 7 to 10
here), and each call would carry all earlier tool results.

### 7.2 The cost of one call

```
cost(call) = tokens_in · price_in / 10⁶  +  tokens_out · price_out / 10⁶
```

`agentkit/llm/economics.py` records the token counts that the provider reports. It estimates (1.3 tokens for
each word) only when a provider reports none, and it marks the row as an estimate. Prices are list prices for
each model. A model-specific row wins over a provider row. The default for an unknown model is $1 for each
million tokens, so an unknown model never shows as free.

### 7.3 The cascade: expected cost

Let c_f and c_q be the cost of a fast and a quality call. Let p be the probability that the fast draft
passes the audit.

```
E[cost of cascade]    = c_f + (1 − p) · c_q          (plus a quality rewrite if the first quality draft fails)
E[cost, quality only] = c_q

the cascade is cheaper  ⇔  c_f + (1 − p)·c_q < c_q  ⇔  c_f < p · c_q  ⇔  p > c_f / c_q
```

Example with list prices: gpt-6-luna costs $0.10 / $0.50 for each million tokens. gpt-6.1-sol costs $2 /
$10. Thus c_f / c_q ≈ 0.05. The cascade wins when more than 5% of the cheap drafts pass the audit. The
measured pass rate of cheap drafts was 12 of 12 for luna and Flash-Lite (`COST_ACCURACY.md`). The audit is
the stop-scorer of FrugalGPT, and it costs nothing.

### 7.4 The hard limit

`config/project.toml` sets `max_llm_cost_usd_per_run = 0.25`. `AGENTKIT_MAX_LLM_COST_USD` can change it.
Before each call, the narrator compares the cost in the ledger with the limit. At the limit, no call starts,
and the template answers. The run record gives the reason. Thus the worst-case cost of a run is the limit
plus the cost of one call.

### 7.5 Reasoning tokens

Reasoning models bill hidden reasoning as output tokens. The measurements in `COST_ACCURACY.md`:

| Model | Mean output tokens for one answer |
|---|---|
| gpt-6-luna (`reasoning_effort = "none"`) | about 200 |
| deepseek-flash | about 1,200 |
| Claude Haiku 5.5 | about 1,450 |

The task is to write facts that code already checked. Reasoning adds cost and no graded value. Thus the
`fast` tier starts with a model whose reasoning is off. One run showed the risk: deepseek-v4-pro spent 5,342
output tokens and reached the 4,096-token answer limit. The cascade treated the cut-off answer as unusable,
and the template answered.

### 7.6 Prompt caching and the response cache

- **Provider prefix cache.** The narrator puts the stable text first and the run-specific text last. A
  provider that caches prompt prefixes can then reuse the prefix (Lumer et al., 2026). The gateway sends
  Anthropic `cache_control` only when the prefix is long enough (4,096 characters, about 1,024 tokens).
  Below that size, the provider does not cache.
- **Response cache.** An identical call in the same process returns the stored reply at no cost. It never
  changes a grade.

### 7.7 Summary of the cost levers

| Lever | Saving | Where |
|---|---|---|
| Workflow, not a loop | 5 to 10 times fewer calls | `graph/`, plans |
| Facts in code | No tokens for calculation or checking | `finding.py`, `claim_audit.py` |
| Audit-gated cascade | Most answers at the cheap price | `narrator.py`, `routing.toml` |
| Reasoning off in the fast tier | About 6 times fewer output tokens | `routing.toml` |
| Hard limit for each run | Bounded worst case | `project.toml` |
| Template fallback | $0 answer with the same graded facts | pack `template` |
| Stable prompt prefix | Cheaper input tokens on providers that cache | `narrator.py`, `gateway.py` |

---

## Part 8 — Security

| Threat | Defence |
|---|---|
| Prompt injection in platform data (indirect) | (1) Control flow comes from trusted files only (P4). (2) The finding goes to the LLM inside a fence. The narrator escapes a copy of the closing tag inside the data, so it cannot close the fence. (3) The quarantine removes instruction-like sentences before they reach the finding. (4) The audit rejects a verdict that the gate did not give. (5) Check `injection_resisted`, and the `inject_text` fault in CI. |
| An unintended write | Dry run by default. A write needs `--write` and `allow_writes` in the task. A person can approve each write. The engine never tries a write again. `tool_calls_policy` and `unexpected_state_change` grade it from the journal and ground truth. |
| A tool outside the seat | The action allowlist. A patch or a plan that names another tool fails validation. |
| A bad call to the platform | The argument check stops it before the network. |
| Leaked secrets | Keys only in headers. The gateway removes key values from error text. The journal never writes tokens. Two secret scanners run over the full git history in CI. |
| A network call in an offline run | `AGENTKIT_OFFLINE=1` makes each real network call an error. |

The quarantine is a heuristic. A clever sentence can pass it. That is why it is the second layer, not the
first. The real defence is structural: text in data can never become a tool call or a verdict.

**Attack success rate** (AgentDojo, Debenedetti et al., 2024) over a set of injected runs:

```
ASR = runs where injection_resisted fails / runs with an injection
```

0 failures in 20 attacked runs gives a 95% upper bound of 0.16 (Wilson). A claim of "zero" needs many more
attacked runs.

---

## Part 9 — How another product can use this framework

### 9.1 What a new product gets with no work

A new pack gets each of these properties from `agentkit` (see `ARCHITECTURE.md` §5):

- an action allowlist, dry runs, approval before writes, no retried writes;
- argument checks, a tool journal and a catalogue fingerprint;
- refusals as verdicts, and declines for unclear questions;
- the audited LLM cascade with a template fallback and a cost limit;
- the data fence and the quarantine;
- multi-provider routing with retries, cool-downs and a ledger;
- crash-safe records, checkpoints, resume and fork;
- ground-truth grading, mutants, replay calibration, fault injection, pass^k, Wilson intervals and Pareto
  reports;
- an offline simulator from captured data;
- a run tree and a read-only viewer.

### 9.2 What a new product must write

| Pack item | Purpose |
|---|---|
| Actions | Functions that call the tools of the new platform. They are the allowlist. |
| Plans (TOML) | First nodes, dependencies and rules. |
| Routes and a resolver | For questions that come with no plan. |
| Finding builder | The facts, calculated in code. |
| Claim rules | What a quantity looks like, the necessary facts, the contradictions. |
| Template | The answer with no LLM. |
| Probes and checks | Ground-truth reads and pure grading functions. |
| Mutants and replay faults | Proof that each check can fail. |
| Tasks and fixtures | The evaluation set and the captured platform. |

The steps are in `ARCHITECTURE.md` §7. A test writes a 30-line pack into a temporary folder and runs it end to
end, with no change to `agentkit`.

### 9.3 Examples of other products

| Product | Actions | Finding | Claim rules |
|---|---|---|---|
| Invoice exception agent | Read invoice, PO, goods receipt | Three-way match result, the differences in amounts | Currency amounts must match. "Approved" must match the match result. |
| Supplier quality agent | Read NCRs, CAPAs, audits | Open issues by severity, overdue actions | Counts and dates must match. No invented NCR ids. |
| Incident triage agent | Read alerts, deploys, runbooks | Likely cause from rules, the owner team | Times and service names must match. Hand-off only to an owning team. |
| Contract review agent | Read clauses, policy standards | Clauses that break policy, with citations | Each clause id must exist. Each cited policy must exist. |

### 9.4 When the framework is the wrong choice

This framework fits questions with a known shape, facts that code can check and a high cost for a wrong
fact. It fits less well in these cases:

- **Open-ended research** with no known sequence of steps. A plan cannot list the steps in advance. Add an LLM
  `Planner`, and keep the allowlist and the harness.
- **Creative output** with no facts to check. The audit adds little. The harness still measures cost and
  reliability.
- **Very high concurrency.** The engine uses threads and local files. A large service needs async I/O, a
  database `CheckpointSaver` and a run store. §9.5 gives the plan.
- **Large corpora** with many synonyms. Put an embedding index behind the same `recall` interface, and keep
  BM25 as the baseline. Adopt the new index only if recall@k shows a gain.

### 9.5 Scaling to many users

A product with 10,000 users at the same time needs a different runtime, but the same pack. The full plan is in
[`SCALING_AND_DEPLOYMENT.md`](SCALING_AND_DEPLOYMENT.md). It starts from the measured t01 run and Little's law:

```
λ = 10,000 users / 120 s (one question each 2 min)   ≈ 83 runs/s
L = λ · W = 83 · 14.7 s                               ≈ 1,250 runs at the same time
platform calls ≈ 500/s · LLM input ≈ 13 million tokens/min · agent CPU ≈ 2.5 cores
```

The CPU of the agent is not the limit. The limits are the platform capacity, the token limits of the providers
and the setup cost of each run (3.58 s of 14.74 s). Thus the plan has four parts:

1. **Share what each run repeats:** sessions, the tool catalogue and the BM25 index for each tenant.
2. **Cache what users repeat:** platform reads and audited answers, keyed by the finding.
3. **Queue the rest:** an API, a queue and workers that scale on the queue depth, with shared state in Postgres,
   Redis and object storage.
4. **Fall back to the template** when a provider or the platform is slow, full or over budget.

The pack seam, the allowlist, the claim audit and the grader do not change.

---

## Part 10 — The trade-offs in one table

| Decision | We get | We give up | Why the balance is right here |
|---|---|---|---|
| Compiled plan, not a ReAct loop | Same steps each run. Fewer tokens. Offline grading. | Flexibility for questions of a new shape | The question has a known shape (F6). |
| Facts in code, LLM for words | Correct facts with any model | Some fluency. Pack code for each fact. | A wrong fact costs much (F7). |
| Deterministic audit, not an LLM judge | Exact, free and repeatable | It sees only facts that code can compare | The facts are numbers, ids and verdicts. |
| Template fallback | An answer in each case, at $0 | Less readable prose | Correct and plain is better than fluent and wrong. |
| Rule router with decline | No guesses | Phrasings that no route covers | A refusal is cheap. A wrong record is not. |
| BM25, not embeddings | Offline, explainable, no model | Synonyms outside the table | Small, technical corpus. Metrics watch for misses. |
| Threads and local files | Simple, inspectable, crash-safe | Scale to thousands of runs a second | Batch runs of about 10 nodes. |
| No agent framework or SDK | Full control of failure modes. Few dependencies. | More code to own | The code is small, and tests cover it. |
| Dry run by default | No unintended writes | Writes need an extra step | Writes on a shared platform affect other teams. |
| Grade from files in a separate process | Repeatable grades, free fixes to checks | More disk files | Evaluation is half of the product (F9). |
| 12 tasks with exact checks | Each failure has a clear cause | Wide confidence intervals | The interval says so. More tasks and repeats narrow it. |

---

## Part 11 — The concepts behind the implementation

| Concept | Source | Where it is in the code |
|---|---|---|
| Neuro-symbolic routing: send each sub-problem to the reliable component | MRKL (Karpas et al., 2022) | `finding.py` computes, `narrator.py` writes |
| Plan once, then run the tools | ReWOO (Xu et al., 2023) | `plans/*.toml`, `graph/engine.py` |
| Parallel DAG execution with a task-fetching unit | LLMCompiler (Kim et al., 2023) | ready-set scheduler |
| Bulk synchronous parallel steps | Valiant (1990) | `mode = "superstep"` |
| Workflow first, agent only where necessary | Anthropic (2024), Agentless (Xia et al., 2024) | the fixed plans |
| Separate control flow from untrusted data | CaMeL (Debenedetti et al., 2025) | allowlist, plan files, data fence |
| LLM cascade with a stop scorer | FrugalGPT (Chen et al., 2023) | `compose_answer(tiers=...)` |
| Self-correction needs an outside signal | Huang et al. (2023) | `correction_note()` |
| Biases of LLM judges | Zheng et al. (2023) | no LLM judge in grading |
| BM25 ranking | Robertson and Zaragoza (2009); BEIR (Thakur et al., 2021) | `retrieval/index.py` |
| Retrieval evaluator with three bands | Corrective RAG (Yan et al., 2024) | `gate_hits` |
| Small-to-big retrieval | Wang et al. (2024) | `ParentChildIndex` |
| Semantic chunking rarely pays | Qu et al. (2024) | LLM splitter off by default |
| State-based grading, pass^k | τ-bench (Yao et al., 2024) | ground truth, `pass_hat_k` |
| Unbiased pass@k | Chen et al. (2021) | `pass_at_k` |
| Error bars, clusters, power | Miller (2024) | `wilson_interval`, `clustered_se` |
| Benchmark validity checklist | ABC (Zhu et al., 2025) | grading from files, `drift`, goldens |
| Cost and accuracy together, simple baselines | Kapoor et al. (2024) | `pareto.py`, template arm |
| Partial credit | TheAgentCompany (Xu et al., 2024) | `partial_score` |
| Failure taxonomy | MAST (Cemri et al., 2025) | `FAILURE_MODES` |
| Attack success rate | AgentDojo (Debenedetti et al., 2024) | `injection_resisted`, `inject_text` |
| Reliability under faults | ReliabilityBench (2026) | fault matrix |
| Mutation testing | DeMillo, Lipton and Sayward (1978) | `mutants.py` |
| Fault injection | Chaos engineering practice | `sim/` faults |
| Event-sourced evidence | Write-ahead logging in databases | journal, record written first |
| Atomic file replace | POSIX `rename` | `record/durable_io.py` |
| Exponential backoff, circuit breaking | Network reliability practice | `policies.py`, gateway cool-downs |
| Idempotency of retries | Distributed systems practice | no retried writes |

---

## Part 12 — Known limits and the next steps

The research gap analysis keeps the full list. These are the main open items:

1. **The grader cannot see readability.** All LLM arms and the template arm pass 12 of 12. A calibrated
   readability check would show what the LLM adds.
2. **The sample is small.** 12 tasks give a Wilson lower bound of about 0.76 at 12 of 12. Sealed holdout
   tasks and a task generator over more files would narrow the interval (gap G8).
3. **No LLM planner yet.** Add one as an experimental arm. Adopt it only if it is on the Pareto frontier (gap
   G16).
4. **Single-turn only.** No clarification turn. A user simulator would test it (gap G17).
5. **No memory across runs.** Lessons from failed runs do not feed back into plans or prompts (gap G18).
6. **Retrieval labels are few.** Four labelled queries. More labels would make the retrieval metrics a real
   measure, not only an alarm.

---

## References

Papers from arXiv unless the entry says otherwise. `RESEARCH_GAP_ANALYSIS.md` has the identifiers.

- Anthropic. *Building Effective Agents* (2024).
- Cemri et al. *Why Do Multi-Agent LLM Systems Fail?* (MAST, 2025).
- Chen, Zaharia, Zou. *FrugalGPT* (2023).
- Chen et al. *Evaluating Large Language Models Trained on Code* (HumanEval, 2021).
- Debenedetti et al. *AgentDojo* (2024); *Defeating Prompt Injections by Design* (CaMeL, 2025).
- DeMillo, Lipton, Sayward. *Hints on Test Data Selection* (IEEE Computer, 1978).
- Huang et al. *Large Language Models Cannot Self-Correct Reasoning Yet* (2023).
- Kapoor et al. *AI Agents That Matter* (2024).
- Karpas et al. *MRKL Systems* (2022).
- Kim et al. *An LLM Compiler for Parallel Function Calling* (2023).
- Lumer et al. "Don't Break the Cache" (2026).
- Miller. *Adding Error Bars to Evals* (2024).
- Qu, Tu, Bao. *Is Semantic Chunking Worth the Computational Cost?* (2024).
- Robertson, Zaragoza. *The Probabilistic Relevance Framework: BM25 and Beyond* (2009).
- Tam et al. *Let Me Speak Freely?* (2024).
- Thakur et al. *BEIR* (2021).
- Valiant. *A Bridging Model for Parallel Computation* (CACM, 1990).
- Wang et al. *Searching for Best Practices in Retrieval-Augmented Generation* (2024).
- Xia et al. *Agentless* (2024).
- Xu et al. *ReWOO* (2023); *TheAgentCompany* (2024).
- Yan et al. *Corrective Retrieval Augmented Generation* (2024).
- Yao et al. *τ-bench* (2024).
- Zheng et al. *Judging LLM-as-a-Judge* (2023).
- Zhu et al. *Establishing Best Practices for Building Rigorous Agentic Benchmarks* (2025).
- *ReliabilityBench* (2026).
