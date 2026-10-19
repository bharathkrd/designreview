+++
id = "pb-13"
title = "Checklists not yet run"
status = "spec"
questions = ["Which design checklists have not been run on the battery tray?"]
tools = ["DesignChecklist.list", "DesignChecklistResult.list"]
tasks = []
triggers = ["on_request"]
writes = false
+++

# PB-13 · Checklists not yet run

## Use case

A file is not ready for review until the checklists for its category are run.

## Design

Read the checklists that apply to the file's industry and category. Read the file's checklist results. Report each checklist with no result.
