+++
id = "pb-10"
title = "Critical characteristics with no tolerance"
status = "spec"
questions = ["Which critical characteristics on the battery tray drawing have no tolerance?"]
tools = ["DesignMarkup.list", "DesignVersion.list"]
tasks = []
triggers = ["on_request"]
writes = false
+++

# PB-10 · Critical characteristics with no tolerance

## Use case

Quality needs a tolerance on each critical characteristic before first-article inspection.

## Design

Read the markups of the newest version. Keep the rows with `is_characteristic = true`. Report each one with no `tol_plus` or no `tol_minus`, by balloon number.

## Limits

The agent reads the markup records, not the drawing. A characteristic with no markup record is not visible to it.
