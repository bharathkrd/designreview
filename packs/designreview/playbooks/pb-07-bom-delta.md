+++
id = "pb-07"
title = "BOM change between versions"
status = "spec"
questions = ["Which BOM lines differ between version 2 and version 3 of the battery tray?"]
tools = ["DesignBOM.list", "DesignVersion.list"]
tasks = []
triggers = ["on_request"]
writes = false
+++

# PB-07 · BOM change between versions

## Use case

A change to a part can add, remove or change lines in its bill of materials. Purchasing and manufacturing need that list.

## Design

Read the versions, map the requested revisions as PB-01 does, then read the `DesignBOM` of each version. Compare the lines in code: added, removed, quantity changed.

## Limits

Suryodaya has only 2 `DesignBOM` rows (GAP_REPORT §6, C-1). Most files have no BOM, so most answers will say "no BOM for this version".
