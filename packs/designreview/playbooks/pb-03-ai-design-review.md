+++
id = "pb-03"
title = "Platform AI design review"
status = "blocked"
plan = "tool_refusal"
questions = ["Run the platform's AI design review on the battery tray and tell me what it finds."]
tools = ["DesignFile.get"]
missing_tools = ["endpoint.designreview.ai_review"]
tasks = ["t03_ai_review_refusal"]
triggers = ["on_request"]
writes = false
blocked_by = "The platform does not offer endpoint.designreview.ai_review to this seat over MCP."
+++

# PB-03 · Platform AI design review

**Plan:** [`plans/tool_refusal.toml`](../plans/tool_refusal.toml)

## When it runs

A person asks the agent to run the platform's own AI review.

## What it does

The plan first checks the seat's tool list for the tool. The tool is not there, so the plan stops all other steps. The answer says plainly that this seat cannot run the AI review. The run calls no platform tool.

## How it becomes live

The platform must give the tool to this seat. Then this playbook needs its own plan, and its status changes to live. The check script then proves the tool is in every seat catalogue.
