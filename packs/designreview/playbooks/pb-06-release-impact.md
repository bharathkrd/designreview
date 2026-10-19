+++
id = "pb-06"
title = "Release impact before a release"
status = "spec"
questions = ["If we release the battery tray, which BOMs, work orders and sales orders does it touch?"]
tools = ["endpoint.designreview.release_impact.get", "endpoint.designreview.release_preview", "endpoint.designreview.release_readiness"]
tasks = []
triggers = ["on_request"]
writes = false
+++

# PB-06 · Release impact before a release

## Use case

Before a release, the engineer must know what the release touches. That is the design BOMs, the BOMs and the open work orders. It is also the items on an older BOM and the open sales demand behind them.

## Design

1. Read the release gate (as PB-01).
2. Read `release_impact.get` and `release_preview` in parallel.
3. Build a finding with the counts and the record ids. Show both views. If they disagree, flag the disagreement and do not pick one.

## Limits

GAP_REPORT §6 (C-1) found that `release_impact.get` lists items through the BOMs of other files. Until the platform fixes it, the answer must label the impact data as unreliable.
