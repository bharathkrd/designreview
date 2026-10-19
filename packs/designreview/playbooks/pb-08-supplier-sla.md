+++
id = "pb-08"
title = "Supplier response time"
status = "spec"
questions = ["Which supplier requests on the battery tray are past their response time?"]
tools = ["endpoint.designreview.supplier_response_sla", "DesignSupplierRequest.list"]
tasks = []
triggers = ["on_request"]
writes = false
+++

# PB-08 · Supplier response time

## Use case

A design review often waits for a supplier answer. The engineer needs to know which requests are late.

## Design

Call `supplier_response_sla` with `operation = "list"` only. Join the queue with `DesignSupplierRequest` on the file. A request is late when `response_due_at` is before today.

## Limits

The same tool also records a response, a reminder or an expiry. Thus the pack treats it as a write tool: a dry run never calls it. A live version of this playbook needs a read action that always sends `operation = "list"`, and a test for that.
