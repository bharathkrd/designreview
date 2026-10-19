+++
id = "pb-12"
title = "Design files shared outside the company"
status = "spec"
questions = ["Who outside the company can see the battery tray files?"]
tools = ["DesignShare.list"]
tasks = []
triggers = ["on_request"]
writes = false
+++

# PB-12 · Design files shared outside the company

## Use case

Security and purchasing must know which suppliers can see which version of a design.

## Design

Read the shares of the file. Group them by recipient company and version. Flag shares of an older version, and shares with no expiry.

## Limits

The answer must not print share tokens. The finding keeps only the recipient name, company, version and type.
