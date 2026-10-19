+++
id = "pb-04"
title = "Wall-thickness analysis"
status = "blocked"
plan = "tool_refusal"
questions = ["Run a wall-thickness analysis on the bench vice."]
tools = ["DesignFile.get"]
missing_tools = ["endpoint.designreview.analysis.thickness"]
tasks = []
triggers = ["on_request"]
writes = false
blocked_by = "The seat has no geometry or thickness tool: endpoint.designreview.analysis.thickness is not offered."
+++

# PB-04 · Wall-thickness analysis

**Plan:** [`plans/tool_refusal.toml`](../plans/tool_refusal.toml) · **Route:** `routes.toml`

## When it runs

A person asks for a geometry analysis: wall thickness or interference.

## What it does

Like PB-03. The plan checks the tool list, finds no thickness tool, and refuses. The answer never estimates a thickness from the commit notes.

## Limits

No task exercises this route yet. PB-03's task t03 tests the same plan with another tool.
