+++
id = "pb-02"
title = "Release readiness, schedule and hand-offs"
status = "live"
plan = "release_handoff"
questions = ["Is the battery tray ready for release, is the project on schedule, and who else needs to act?", "Does anything on the auger drive housing cover need another team?"]
tools = ["DesignFile.get", "endpoint.designreview.release_readiness", "DesignFeedback.list", "DesignChecklistResult.list", "DesignMilestone.list", "AgentEscalation.list", "endpoint.agent_governance.escalations.assignees", "AgentSession.create", "endpoint.agent_governance.escalations.raise", "AgentSession.close.active.closed"]
tasks = ["t08_battery_tray_handoff", "t09_keystone_no_handoff_late_schedule", "t12_routed_keystone_schedule"]
triggers = ["on_request"]
writes = true
+++

# PB-02 · Release readiness, schedule and hand-offs

**Plan:** [`plans/release_handoff.toml`](../plans/release_handoff.toml) · **Topics:** [`handoffs.toml`](../handoffs.toml) · **Code:** `handoffs.py`

## When it runs

A person asks if a part can go to release, if its project is on time, or who must act on its open problems.

## What it reads

1. The design file, then in parallel the release gate, the feedback and the project milestones.
2. The open serious items: gate blockers and feedback with high or critical severity.
3. The hand-off topics in `handoffs.toml`. Each topic has an owner and keywords.

## What it checks

- A milestone is past due when its due date is before today and its status is not completed or skipped.
- An open serious item whose title matches a topic gets one hand-off for that owner. The hand-off cites every matched item.
- Items that are the design team's own work get no hand-off.

## Writes

This is the only playbook that writes. The run files an escalation only with `--write` and a task that has `allow_writes`. A dry run records the exact calls and files nothing. The run never retries a write, and it skips a hand-off whose escalation is already open.

## How the answer reads

Release readiness, schedule, and who needs to act. After a dry run, the answer calls the hand-offs proposals and says that the agent filed nothing. The answer never says "on schedule" while a milestone is past due.

## Limits

Keystone has no person the seat can assign, so on Keystone the run declines to file and says why. The keyword match is plain text. A blocker title with no keyword gets no hand-off.
