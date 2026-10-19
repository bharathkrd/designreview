+++
id = "pb-14"
title = "Daily digest of blocked release gates"
status = "spec"
questions = ["Each morning, list the design files whose release gate has blockers."]
tools = ["DesignFile.list", "endpoint.designreview.release_readiness"]
tasks = []
triggers = ["scheduled:daily"]
writes = false
+++

# PB-14 · Daily digest of blocked release gates

## Use case

A design lead wants one list each morning, without asking for it.

## Design

A scheduled run reads every file in a review state and its release gate. It lists the files with blockers, the new blockers since yesterday, and the blockers that cleared.

## Limits

The agent has no scheduler today: it answers only when asked. This needs a trigger outside the agent (a cron job or a platform job) and a store for yesterday's list.
