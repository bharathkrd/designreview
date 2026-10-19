+++
id = "pb-05"
title = "Release a design file"
status = "blocked"
plan = "route_declined"
questions = ["Release the battery tray to production now."]
tools = ["endpoint.designreview.release_impact"]
tasks = []
triggers = ["on_request"]
writes = true
blocked_by = "Release needs the design_admin role, and this seat is design_user. A release is a person's decision."
+++

# PB-05 · Release a design file

**Plan:** [`plans/route_declined.toml`](../plans/route_declined.toml)

## When it runs

A person asks the agent to release a file: to move it from ready to approved.

## What it does

No route matches a release request, so the router declines it. The run reads nothing and writes nothing.

## Why it stays blocked

- `endpoint.designreview.release_impact` releases the newest version (`action = "release"`). It is a write, not a read.
- The platform gates the release on the `design_admin` role.
- A release commits the company to build the part. The agent can prepare the evidence (PB-01, PB-06). A person makes the decision.

## Limits

A release request that also says "manufacturing" matches PB-01's route. That run is a read-only review, so it is safe, but it does not answer the request directly.
