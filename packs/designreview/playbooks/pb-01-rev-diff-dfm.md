+++
id = "pb-01"
title = "Revision change and manufacturability review"
status = "live"
plan = "rev_diff_dfm"
questions = ["What changed between rev B and rev C of the battery tray, and are there manufacturability problems?", "What changed in the latest revision of the auger drive housing cover?"]
tools = ["DesignFile.get", "DesignVersion.list", "endpoint.designreview.release_readiness", "DesignFeedback.list", "DesignChecklistResult.list", "DesignStandard.list"]
tasks = ["t01_battery_tray_rev_diff", "t02_unknown_file_refusal", "t04_bench_vice_no_geometry", "t05_propeller_rev_mapping", "t06_keystone_boilerplate_notes", "t07_keystone_latest_dfm_fixes", "t10_routed_battery_tray", "t11_routed_ambiguous_propeller"]
triggers = ["on_request"]
writes = false
+++

# PB-01 · Revision change and manufacturability review

**Plan:** [`plans/rev_diff_dfm.toml`](../plans/rev_diff_dfm.toml) · **Finding:** `finding.py` · **Checks:** `checks.py`

## When it runs

A design engineer asks what changed between two revisions of a part, or in its latest revision. The question can also ask about manufacturability or release readiness.

## What it reads

1. The design file. If the file does not exist, the plan stops all other reads and the run ends as one refusal.
2. In parallel: the versions, the release gate and the feedback.
3. The company design standards that match the change notes and the blockers (BM25, with a relevance gate).
4. If the gate shows a blocker, or the gate read fails, the failed checklist results.

## What it checks

- The version that each requested revision letter maps to. The letter comes from the commit message, not from the version order.
- The quantities in the commit notes, quoted exactly.
- The gate verdict, its reasons, and the open critical feedback.
- The standards it cites must exist on the platform.

## How the answer reads

Summary, what changed, manufacturability, release readiness, and anything not available. Manufacturability text is engineering judgement and says so. The answer makes no geometry claim: the seat has no geometry tool.

## Limits

The seat cannot measure the model. Boilerplate commit notes ("drawing and model updated together") give no change detail, and the answer says so. A part name that matches two files gets a refusal that names both files.
