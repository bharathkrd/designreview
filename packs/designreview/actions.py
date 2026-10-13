"""
Design-review graph actions: the complete allowlist of what a plan or the
planner may do on this seat. All are reads; there is no write action yet,
so a plan cannot change platform data at all.

Tool names and argument shapes are the live seat catalogue (Entity.verb,
flat kwargs), confirmed 2026-09-28. `endpoint.designreview.compare`,
`measure` and `upload` are no longer offered to this seat, so nothing here
relies on them.
"""

from __future__ import annotations

from typing import Any, Dict

from agentkit.graph import RESOLVED, RunEnv, declined
from agentkit.registry import Registry
from agentkit.retrieval import ParentChildIndex, ParentDoc, plain_text
from agentkit.transport.safe_reads import read_all, sort_rows

# Computed endpoints this pack calls that are reads despite not ending in
# .list/.get -- the journal and the dry-run policy check rely on this list.
READ_ONLY_ENDPOINTS = (
    "endpoint.designreview.release_readiness",
    "endpoint.designreview.release_impact",
    "endpoint.designreview.release_impact.get",
    "endpoint.designreview.parts_search",
    "endpoint.designreview.supplier_response_sla",
)

# Filters the platform applies exactly (one scalar value, no operator). Lists
# are read in full through agentkit.transport.safe_reads.read_all, which pages
# past any page cap, sorts in code (the server's sort_order isn't validated)
# and re-checks every filter on the rows it gets back.
SAFE_SERVER_FILTERS = ("file_id", "project_id", "overall_result")

# The tools this pack's actions and probes depend on, with the arguments they
# send; recorded per run (taskrun.tool_catalog) and checked by
# `python -m agentkit.harness.preflight`. Write tools are listed separately.
REQUIRED_TOOLS = {
    "DesignFile.get": ["id"],
    "DesignVersion.list": ["file_id", "limit", "offset"],
    "endpoint.designreview.release_readiness": ["file_id"],
    "DesignFeedback.list": ["file_id", "limit", "offset"],
    "DesignChecklistResult.list": ["file_id", "overall_result", "limit", "offset"],
    "DesignStandard.list": ["limit", "offset"],
    "DesignMilestone.list": ["project_id", "limit", "offset"],
}


def register_actions(reg: Registry) -> None:
    reg.declare_read_only(READ_ONLY_ENDPOINTS)
    reg.extras["required_tools"] = dict(REQUIRED_TOOLS)

    @reg.action("load_design_file", retries=2, description="DesignFile.get for one file.")
    def load_design_file(env: RunEnv, args: Dict[str, Any], results) -> Any:
        return env.client.invoke_tool("DesignFile.get", {"id": args["file_id"]})

    @reg.action("list_revisions", retries=2,
                description="Every DesignVersion of a file, oldest first, with commit messages.")
    def list_revisions(env: RunEnv, args: Dict[str, Any], results) -> Any:
        page = read_all(env.client, "DesignVersion.list", {"file_id": args["file_id"]},
                        safe_keys=SAFE_SERVER_FILTERS)
        return {**page, "data": sort_rows(page["data"], "version_number")}

    @reg.action("read_release_gate", retries=2,
                description="Aggregated release-readiness evidence (ready, reason codes, blockers).")
    def read_release_gate(env: RunEnv, args: Dict[str, Any], results) -> Any:
        return env.client.invoke_tool("endpoint.designreview.release_readiness", {"file_id": args["file_id"]})

    @reg.action("list_feedback", retries=2, description="DesignFeedback rows for a file.")
    def list_feedback(env: RunEnv, args: Dict[str, Any], results) -> Any:
        return read_all(env.client, "DesignFeedback.list", {"file_id": args["file_id"]},
                        safe_keys=SAFE_SERVER_FILTERS)

    @reg.action("list_failed_checklists", retries=2,
                description="DesignChecklistResult rows for a file whose overall result is fail.")
    def list_failed_checklists(env: RunEnv, args: Dict[str, Any], results) -> Any:
        return read_all(env.client, "DesignChecklistResult.list",
                        {"file_id": args["file_id"], "overall_result": "fail"}, safe_keys=SAFE_SERVER_FILTERS)

    @reg.action("probe_tool_offered",
                description="Refuse up front when the tool a request needs is not in this seat's catalogue.")
    def probe_tool_offered(env: RunEnv, args: Dict[str, Any], results) -> Any:
        tool = args["tool"]
        if not env.client.offers(tool):
            return declined(f"{tool} is not available to this seat (absent from tools/list)",
                            data={"tool": tool, "offered": False}, error_kind="not_in_seat")
        return {"tool": tool, "offered": True}

    @reg.action("decline", description="A refusal decided at planning time; args carry the reason.")
    def decline(env: RunEnv, args: Dict[str, Any], results) -> Any:
        return declined(args.get("reason", "request declined"), data=dict(args))


# ---------------------------------------------------------------- DFM standards retrieval

STANDARDS_PAGE = 100
STANDARDS_MAX_PAGES = 10
STANDARDS_TOP_K = 5
STANDARD_TEXT_CHARS = 300  # how much of each matched standard the action returns


def _all_rows(client, tool: str, args: Dict[str, Any], page: int = STANDARDS_PAGE,
              max_pages: int = STANDARDS_MAX_PAGES) -> list:
    """Page a .list tool through env.client.invoke_tool, so every page is journaled."""
    rows, offset = [], 0
    for _ in range(max_pages):
        payload = client.invoke_tool(tool, {**args, "limit": page, "offset": offset})
        batch = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(batch, list):
            break
        rows.extend(r for r in batch if isinstance(r, dict))
        offset += len(batch)
        total = payload.get("total")
        if not batch or len(batch) < page or (total is not None and offset >= int(total)):
            break
    return rows


def standards_query(results) -> str:
    """What to look standards up by: the change notes being reviewed plus the
    release blockers' titles. The plan makes this node wait for both reads,
    so the query never depends on which one finished first."""
    parts = []
    rev = results.get("revisions")
    if rev is not None and rev.verdict == RESOLVED and isinstance(rev.data, dict):
        rows = sorted((r for r in rev.data.get("data") or [] if isinstance(r, dict)),
                      key=lambda r: r.get("version_number") or 0)
        parts += [r.get("commit_message") or "" for r in rows[-2:]]
    gate = results.get("release_gate")
    if gate is not None and gate.verdict == RESOLVED and isinstance(gate.data, dict):
        g = gate.data.get("result", gate.data)
        parts += [b.get("title") or "" for b in g.get("blockers") or [] if isinstance(b, dict)]
    return " ".join(p for p in parts if p)


def register_retrieval(reg: Registry) -> None:
    @reg.action("gather_dfm_standards", retries=2,
                description="Index the company's DesignStandard records and recall those relevant to the change.")
    def gather_dfm_standards(env: RunEnv, args: Dict[str, Any], results) -> Any:
        """Search small, return whole: each standard record is a parent, its
        sections/topic chunks are the children BM25 matches against, and a
        match returns the whole record (agentkit.retrieval.ParentChildIndex)."""
        rows = _all_rows(env.client, "DesignStandard.list", {})
        docs = []
        for i, r in enumerate(rows):
            body = "\n".join(x for x in (r.get("name") or "", plain_text(r.get("description") or "")) if x)
            meta = {k: r.get(k) for k in ("name", "category", "standard_body", "standard_number", "is_active")}
            # Active records first, so the per-name dedupe below keeps an active one when ranks tie.
            meta["_rank"] = 0 if r.get("is_active") in (1, True) else 1
            # Seed data repeats standard names across records; one hit per base name.
            meta["base_name"] = (meta.get("name") or "").split("—")[0].strip().lower()
            docs.append(ParentDoc(id=r.get("id") or f"row-{i}", text=body, meta=meta, entity="DesignStandard"))
        index = ParentChildIndex()
        index.add_documents(docs)
        query = args.get("query") or standards_query(results)
        categories = args.get("categories")
        hits = index.recall_parents(query, k=args.get("k", STANDARDS_TOP_K),
                                    where={"category": categories} if categories else None, distinct_by="base_name")
        return {"query": query, "indexed_records": len(rows), "indexed_passages": len(index.index),
                "matches": [{"id": h.parent.id,
                             **{k: v for k, v in h.parent.meta.items() if not k.startswith("_") and k != "base_name"},
                             "score": h.score, "matched_terms": h.matched,
                             "section": h.children[0].passage.meta.get("header_path") or [],
                             "passage": h.parent.text[:STANDARD_TEXT_CHARS]} for h in hits]}
