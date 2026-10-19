"""
Offline tests for agentkit/graph (LiveGraphExecutor, GraphStore, GraphPatch, RulePlanner).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Use cases to cover:
  [ ] Nodes with no dependencies all run; results() is keyed by node id
  [ ] A node with requires="resolved" runs only after every dependency RESOLVED
  [ ] A DECLINED or FAILED dependency leaves its dependants BYPASSED (with the reason), never resolved
  [ ] requires="settled" still runs when one dependency failed (partial join)
  [ ] A platform "not found" (SeatCallFailure kind MISSING) ends the node DECLINED, not FAILED
  [ ] A FLAKY error is retried up to the action's `retries`; a write action is never retried
  [ ] A write action in a dry run is never called: DECLINED without a preview; HANDED_OFF with
      data {"would_file": <preview>, "filed": False} with one; RESOLVED when the preview is empty
  [ ] A preview on a read action is rejected at registration
  [ ] A patch naming an action that is not registered is rejected (raw tool names can't be planned)
  [ ] A dependency cycle is rejected and the graph is left exactly as it was
  [ ] The node budget (max_nodes) is enforced
  [ ] The rev_diff_dfm rule adds failed_checklists when release_gate has blockers/reason codes, and the
      fallback rule adds it when release_gate FAILED; a clear gate adds nothing
  [ ] That rule fires at most once
  [ ] A checkpoint is written and a run can resume from it (mid-flight nodes run again)
Since 2026-10-13 (agentkit/graph/policies.py, channels.py, checkpoint.py):
  [ ] RetryPolicy: waits are min(max_interval, initial * backoff**(n-1)); max_attempts includes the first try;
      retries=2 still waits backoff, 2*backoff; a write action gets one attempt whatever its policy
  [ ] superstep mode: siblings in one step never see each other's results; a Topic channel written by three
      siblings that sleep random times always ends in node-id order
  [ ] two siblings writing one LastValue channel in the same superstep raise ChannelConflict
  [ ] Barrier(["a", "b"]) has no value until both names arrive
  [ ] a long chain in superstep mode with max_steps too small raises StepLimitExceeded
  [ ] an action calling interrupt() pauses its node (no verdict), dependants wait, the rest finish;
      store.resume(node, answer) + continue_from() and interrupt() returns the answer
  [ ] approve_writes=True: a real write pauses with its preview; anything but {"approved": True} -> DECLINED
  [ ] with a MemorySaver: one "input" checkpoint, then one "loop" checkpoint per outcome, each pointing at its parent
  [ ] fork({node: new_result}): downstream plan nodes go back to pending, planner-added nodes disappear,
      the original store is unchanged
Since 2026-10-14 / 2026-10-15:
  [ ] @registry.action(name, timeout_s=0.1) on an action that sleeps 1 s -> the node ends FAILED with
      error_kind "timeout"; a sibling branch still finishes
  [ ] a rule with verdict = "failed" and no data condition is valid; the same rule with verdict "resolved"
      and no condition is rejected; verdict = "exploded" is rejected
  [ ] a fallback node with requires = "settled" runs after its dependency FAILED (with "resolved" it would
      be bypassed)
More use cases (added 2026-10-16, to write by hand):
  [ ] the same plan run twice with the same fake client gives the same verdict and data for every node
  [ ] an action that raises a plain Exception ends its node FAILED with the error text; independent
      siblings still finish and results() has every node
  [ ] a node that is BYPASSED is never passed to its action (the fake action records no call)
Hint: build a Registry with small fake actions, and use RunEnv(client=<fake with invoke_tool>),
so no MCP is needed. Plans: agentkit.graph.load_plan("packs/designreview/plans/rev_diff_dfm.toml").
"""

import pytest

from agentkit.graph import GraphPatch, GraphStore, LiveGraphExecutor, RulePlanner, RunEnv, TaskSpec, load_plan
from agentkit.graph import MemorySaver, NodeResult, RetryPolicy, interrupt
from agentkit.registry import Registry, load_pack

# Write your tests below.
