# `agentkit/graph/` — the live task graph

*Reading order: **3rd**. Files: `engine.py`, `node_result.py`, `plan_loader.py`, `rule_planner.py`,
`policies.py`, `channels.py`, `checkpoint.py`; plus `agentkit/registry.py` and `agentkit/agents/planned.py`.*

## 10,000-ft view

A plan (TOML) lists the first nodes; nodes run as soon as their dependencies allow, in parallel on a thread
pool; after each node finishes, declarative rules may add follow-up nodes. Every node ends with a verdict, and
the whole graph is checkpointed after every step.

## Why it's written this way

- **Traced (since 2026-10-12).** Each executed node is a `node` span (action, verdict, attempts, queue wait)
  and each planner call a `step` span; the engine submits work with `agentkit.telemetry.bind_context` so spans
  opened in pool threads nest under the run's task span. Retries are span events. See `agentkit_telemetry.md`.

- **Verdicts, not success/failure.** `resolved`, `declined` (a refusal — normal, not a crash), `handed_off`,
  `failed`, `bypassed` (never ran because a dependency it required didn't resolve). A refusal therefore doesn't
  take the answer down with it.
- **`requires = "resolved" | "settled"`.** `resolved`: run only if every dependency resolved, else bypass with
  the reason. `settled`: run once every dependency finished in any verdict — a partial join.
- **Actions are an allowlist.** A node names a registered *action*, never a raw tool. A patch naming anything
  else is rejected, so neither a plan nor the planner can reach a tool the pack didn't expose. A write action
  is never called in a dry run. If it registers a `preview`, the engine calls that instead and the node ends
  `handed_off` with `{"would_file": ..., "filed": false}` (an empty preview is `resolved`, "nothing to file");
  without a preview it is `declined`. The design-review pack's only write action, `raise_handoffs`, is
  preview-only.
- **Transport errors map to verdicts.** `missing`, `not_in_seat`, `denied` → declined; `flaky` → retried per
  the action's retry policy (never for writes) then failed; anything else → failed; a bug in an action → failed
  with `error_kind = "internal"`, siblings keep running.
- **Retry policy (since 2026-10-13, `policies.py`).** `RetryPolicy(max_attempts, initial_interval,
  backoff_factor, max_interval, jitter, retry_on)`: wait `min(max_interval, initial × backoff^(n−1))` (+0–1 s
  jitter when on) before attempt n+1; `max_attempts` includes the first try; `retry_on` is exception types or a
  predicate, by default "a FLAKY transport failure". Before: only `retries=<int>` with hard-coded doubling.
  `retries=n` still works and means exactly the old waits (`RetryPolicy.from_retries`). Writes: always one
  attempt. Jitter is off by default so offline runs wait the same every time.
- **Patches are all-or-nothing.** Unknown action, duplicate id, missing dependency, an edge into a node that
  already started, a cycle, or exceeding the node budget (30) raises before anything changes.
- **Resumable checkpoints.** `graph.json` (format `agentkit-graph-v1`) round-trips; nodes that were mid-flight
  when a run died go back to pending on resume. Since 2026-10-13 it may also carry `channels` (only when a
  plan declares some) and, per node, `interrupt` / `resume` (only on a paused node); ordinary runs write the
  same file as before.

### Since 2026-10-13: modes, channels, pausing, history

| Feature | Before | After |
|---|---|---|
| Scheduling | eager only: a node starts as soon as it can; the planner sees outcomes in finishing order | still the default. **`mode = "superstep"`** (plan file or `run_plan(mode=)`): every ready node runs in parallel on the same snapshot; when all finish, outcomes are recorded, channel writes applied and the planner consulted **in node-id order** — thread timing can't change state, patches or checkpoints. `max_steps` (50) → `StepLimitExceeded` |
| Shared state | none: each node writes only its own `NodeResult` | optional **channels** declared in the plan (`[channels]`): `last_value`, `topic` (append), `reducer` (`sum`/`max`/`min`/`extend`/`merge`/`union`, with `Overwrite`), `ephemeral`, `barrier` (join). A node writes `NodeResult(writes={...})`; an action reads `read_channels()`. Two writers of a `last_value` in one superstep is `ChannelConflict` — a race made into an error |
| Pausing for a person | not possible | an action calls `interrupt(payload)`: the node is **paused** (no verdict), dependants wait, everything else finishes; `store.resume(node, answer)` + `continue_from()` re-runs it and `interrupt()` returns the answer. `approve_writes=True` does this before every real write with the write's preview; only `True` / `{"approved": true}` lets it run, anything else → `declined` |
| History | `graph.json` = latest state only | with a `CheckpointSaver` (`MemorySaver`, `JsonlSaver` → `checkpoints.jsonl`) every step is also a checkpoint `{id, ts, parent_id, metadata{source: input/loop/fork, step, nodes, ran}, graph}`; ids sort by time; `store.history(before=, limit=, filter=)` newest first. Off unless a saver is given |
| Fork | — | `store.fork({node: NodeResult}, from_checkpoint=None)`: a new store with those results replaced; everything downstream is undone (plan nodes → pending, planner-added nodes removed so rules decide again); channels rebuilt; the source is untouched. Basis of `agentkit.harness.replay` |
| Rules | could fire twice and collide after a re-run | a rule never adds a node id that already exists or links into one that started |

Value, honestly: the shipped plans stay eager (superstep gives the same findings on all nine offline tasks
— a test checks this — but waits for the slowest node each step). The parts in daily use are the retry
policy, fork/replay (end-to-end calibration in CI) and the approval gate for live writes.
- **Plans and rules are data**, validated by pydantic (`PlanModel`, `NodeModel`, `RuleModel`, `WhenModel`):
  unknown keys, a bad `requires`, a rule with no condition or no effect are rejected at load time. Placeholders
  like `"{file_id}"` are filled from run parameters (types kept); an unknown placeholder is an error.

## What it does

`run_plan(env, registry, plan)` builds a `LiveGraphExecutor` with a `RulePlanner` over the plan's rules and
returns the `GraphStore`. `record_steps(run, store)` copies each node's verdict, reason, error kind, attempts,
who added it and timing into the run record. `answer_with_pack(...)` (see `agentkit_answer.md`) builds the
finding and the answer.

A rule, in TOML:

```toml
[[rules]]
name = "failed_checklists_when_gate_blocked"
[rules.when]
node = "release_gate"
nonempty = ["result.blockers", "result.reason_codes"]   # or equals / truthy / falsy
[[rules.add]]
id = "failed_checklists"
action = "list_failed_checklists"
args = { file_id = "{file_id}" }
after = ["release_gate"]
```

## Key types

| Name | Purpose |
|---|---|
| `RunEnv(client, run_id, params, dry_run, tenant, gateway)` | what an action receives besides its args |
| `TaskSpec` | one node: id, action, args, after, requires, result, attempts, timing |
| `GraphPatch(add, link)` | the only way to change the graph |
| `GraphStore` | nodes + validation + ready-set + checkpoint; `channels`, `paused()`, `resume()`, `history()`, `fork()` |
| `LiveGraphExecutor(mode=, channels=, saver=, approve_writes=, max_steps=)` | runs the ready set, applies planner patches |
| `NodeResult(verdict, data, reason, error_kind, writes)` | how a node ended (+ optional channel writes) |
| `RetryPolicy` | when and how long to wait before trying an action again |
| `Channel` types, `ChannelState` | shared state with declared merge rules |
| `Checkpoint`, `MemorySaver`, `JsonlSaver` | history |
| `interrupt()`, `approved()` | pause a node for a person |
| `Registry` / `ActionSpec` | a pack's actions (with `retries` or `retry`, `writes`, and `preview` for a write action), probes, checks, mutants, replay faults, extras |

## How to test

`tests/test_dag_engine.py` — a `Registry()` with small fake actions and a fake client; no MCP needed.
For the 2026-10-13 features: a `random.uniform` sleep inside an action scrambles finishing order (superstep
results must not change); `MemorySaver` + `fork` on a three-node graph; an action that calls `interrupt()`.

*The modes, channels, pause/resume and checkpoint history are adapted from an external open-source
agent-graph design (referred to from outside sources) and rewritten here in plain Python; nothing from it is
imported or required.*

## Action timeouts (since 2026-10-14)

`@registry.action(name, timeout_s=...)`: each attempt runs in its own thread (with the node's context) and the
engine stops waiting after `timeout_s`; the node ends FAILED with `error_kind="timeout"` and the other branches
carry on. A Python thread can't be killed, so the abandoned attempt finishes in the background and its result is
ignored -- give timeouts to read actions only.

