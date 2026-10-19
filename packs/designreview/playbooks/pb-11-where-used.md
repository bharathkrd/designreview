+++
id = "pb-11"
title = "Assemblies that use a part"
status = "spec"
questions = ["Which assemblies use the mounting bracket?"]
tools = ["endpoint.designreview.parts_search", "DesignAssembly.list"]
tasks = []
triggers = ["on_request"]
writes = false
+++

# PB-11 · Assemblies that use a part

## Use case

Before a change, the engineer must know every assembly that uses the part.

## Design

Search the assembly tree with `parts_search`. Join the hits with `DesignAssembly` for names and status. The router resolves the part name as it does for PB-01.

## Limits

The platform marks `parts_search` as not read-only, but its description is a search. The pack lists it as a read. A live version must confirm with a captured call that it changes nothing.
