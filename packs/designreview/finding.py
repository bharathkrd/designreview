"""
build_finding(): the gradable answer, computed in code from node results.

The LLM never decides a fact. Everything a verifier grades lives here:

  outcome          answered | partial | declined
  file             id / number / name / status / current_version
  revision_delta   which version is rev X / rev Y (from commit messages),
                   each version's commit note + the quantities it states,
                   basis = "commit_message", geometry_compared = False
  release_gate     ready, reason codes/reasons, critical_open, blockers
  dfm_signals      failed checklist results + open high/critical feedback +
                   DesignStandard records recalled for the change (keyword match)
  schedule         the project's milestones with due dates; past_due is
                   computed from the snapshot date (the platform leaves a
                   late milestone's status at in_progress)
  handoffs         proposed hand-offs to the teams that own problems this
                   seat can't fix (handoffs.toml), each citing the open
                   items behind it, plus what would be filed -- in a dry
                   run nothing is filed (filed = false)
  declines         every node the platform refused, with its reason
  quarantined      instruction-like sentences removed from platform text
                   (agentkit.answer.quarantine) -- planted text never reaches
                   the answer; each entry says where it was found

A section built from a list the platform returned only in part ("complete":
False from read_all) is "partial" and says how many rows came back.

Sections whose nodes are not in the plan are left out, and the outcome
only counts the sections that are present.

Why commit messages: in this build diff_from_parent_json only carries file
hashes and no CAD kernel exists (PLAN.md §8), so the revision delta can
only come from the engineers' own version notes -- and the finding says so.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from agentkit.answer.quarantine import quarantine_instructions
from agentkit.clock import now_utc
from agentkit.graph import DECLINED, FAILED, RESOLVED, NodeResult
from packs.designreview.handoffs import milestone_view

FINDING_SCHEMA = "designreview-finding-v1"
REV_RE = re.compile(r"\brev(?:ision)?\.?\s+([A-Z]|\d{1,2})\b", re.I)  # "rev B", "Rev 2"
QUANTITY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|°|deg|degrees?|kg|g|%)(?![A-Za-z])", re.I)
CLOSED_FEEDBACK = {"resolved", "closed", "rejected", "wont_fix", "won't_fix", "cancelled", "duplicate"}
SERIOUS = {"critical", "high"}
FILE_KEYS = ("id", "number", "name", "status", "current_version", "released_version_id", "has_brep",
             "conversion_status")


def rev_letter(commit_message: str) -> Optional[str]:
    m = REV_RE.search(commit_message or "")
    return m.group(1).upper() if m else None


def requested_revs(prompt: str) -> List[str]:
    """Rev letters named in the question, in order, de-duplicated."""
    seen: List[str] = []
    for letter in REV_RE.findall(prompt or ""):
        if letter.upper() not in seen:
            seen.append(letter.upper())
    return seen


# One rev in a "compare X with Y" phrase: "rev B", "Revision 2", "rev. C"; a bare capital letter
# ("from B to C") only inside the between/from forms, where it can't be an article or a quantity.
_PREFIXED_REV = r"(?i:rev(?:ision)?s?)\.?\s+(?:[A-Za-z]|\d{1,2})\b"
_ANY_REV = rf"(?:{_PREFIXED_REV}|\b[A-Z]\b)"
_PAIR_RE = re.compile(rf"\b(?i:between)\s+{_ANY_REV}\s+(?i:and)\s+{_ANY_REV}"
                      rf"|\b(?i:from)\s+{_ANY_REV}\s+(?i:to)\s+{_ANY_REV}"
                      rf"|{_PREFIXED_REV}\s*(?:->|→|=>|\b(?i:to|vs|versus)\b\.?)\s*{_PREFIXED_REV}")
_REV_TOKEN = re.compile(r"(?i:rev(?:ision)?s?)\.?\s+([A-Za-z]|\d{1,2})\b|\b([A-Z])\b")


def requested_pair(prompt: str) -> Optional[List[str]]:
    """The two revs the question asks to compare ("between rev B and rev C", "from B to C",
    "rev B -> rev C"), from -> to; None when no such phrase names two different revs.
    Revs mentioned elsewhere ("Rev A was the prototype.") don't count."""
    m = _PAIR_RE.search(prompt or "")
    if not m:
        return None
    revs = [(a or b).upper() for a, b in _REV_TOKEN.findall(m.group(0))]
    return revs[:2] if len(revs) >= 2 and revs[0] != revs[1] else None


def quantities(text: str) -> List[Dict[str, Any]]:
    return [{"value": float(v), "unit": u.lower(), "text": f"{v} {u}"} for v, u in QUANTITY_RE.findall(text or "")]


def _data(results: Dict[str, NodeResult], node: str) -> Optional[Any]:
    r = results.get(node)
    return r.data if r is not None and r.verdict == RESOLVED else None


def _section_state(results: Dict[str, NodeResult], node: str) -> Dict[str, Any]:
    r = results.get(node)
    if r is None:
        return {"outcome": "not_run"}
    if r.verdict == RESOLVED:
        return {"outcome": "answered"}
    out = {"outcome": "declined" if r.verdict == DECLINED else ("error" if r.verdict == FAILED else r.verdict),
           "reason": r.reason}
    if r.error_kind:
        out["error_kind"] = r.error_kind
    return out


def _incomplete(results: Dict[str, NodeResult], node: str) -> Optional[str]:
    """Why `node`'s list is incomplete, or None when it is whole."""
    payload = _data(results, node)
    if isinstance(payload, dict) and payload.get("complete") is False:
        return (f"the platform returned {payload.get('received')} of {payload.get('server_total')} "
                f"rows for {node}")
    return None


def _clean(text: Any, where: str, quarantined: List[Dict[str, str]]) -> Any:
    """Platform text with instruction-like sentences removed (recorded in `quarantined`)."""
    if not isinstance(text, str):
        return text
    kept, dropped = quarantine_instructions(text)
    # Only where it was and how long: the finding is shown to the LLM, the planted text must not be.
    quarantined.extend({"where": where, "words": len(s.split())} for s in dropped)
    return kept


def _rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [r for r in payload["data"] if isinstance(r, dict)]
    return []


def _revision_delta(results: Dict[str, NodeResult], prompt: str,
                    quarantined: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    quarantined = [] if quarantined is None else quarantined
    section = _section_state(results, "revisions")
    if section["outcome"] != "answered":
        return section
    rows = _rows(_data(results, "revisions"))
    if rows and not any("commit_message" in r for r in rows):
        section.update(outcome="declined", reason="the version records carry no commit_message field (the "
                       "platform's schema has changed?), so the revision letters can't be read")
        return section
    versions = []
    for row in sorted(rows, key=lambda r: r.get("version_number") or 0):
        note = _clean(row.get("commit_message") or "", f"commit message of v{row.get('version_number')}",
                      quarantined)
        versions.append({"version_number": row.get("version_number"), "id": row.get("id"),
                         "rev": rev_letter(note), "commit_message": note, "quantities": quantities(note)})
    section.update(basis="commit_message", geometry_compared=False,
                   basis_note="diff_from_parent_json only records file hashes in this build; no geometry "
                              "comparison was run. Changes come from the version commit messages.",
                   versions=versions)
    if not versions:
        section.update(outcome="declined", reason="this file has no versions")
        return section

    named = requested_revs(prompt)
    wanted = requested_pair(prompt) or (named if len(named) == 2 else [])
    if not wanted and len(named) > 2:
        # Three or more revs and no "between X and Y": picking two would be a guess.
        section.update(outcome="declined",
                       reason=f"the question names revs {', '.join(named)} but not which two to compare")
        return section
    if len(wanted) >= 2:
        by_rev = {v["rev"]: v for v in versions if v["rev"]}
        missing = [r for r in wanted[:2] if r not in by_rev]
        section["requested"] = {"from": wanted[0], "to": wanted[1]}
        if missing:
            section.update(outcome="declined",
                           reason=f"rev {', '.join(missing)} not found in this file's version history "
                                  f"(revs present: {', '.join(sorted(by_rev)) or 'none'})")
            return section
        frm, to = by_rev[wanted[0]], by_rev[wanted[1]]
        section.update(from_version=frm["version_number"], to_version=to["version_number"],
                       change_notes=[v["commit_message"] for v in versions
                                     if frm["version_number"] < v["version_number"] <= to["version_number"]])
    else:
        latest = versions[-1]
        section.update(to_version=latest["version_number"],
                       from_version=versions[-2]["version_number"] if len(versions) > 1 else None,
                       change_notes=[latest["commit_message"]])
    return section


def _release_gate(results: Dict[str, NodeResult]) -> Dict[str, Any]:
    section = _section_state(results, "release_gate")
    if section["outcome"] != "answered":
        return section
    payload = _data(results, "release_gate") or {}
    gate = payload.get("result", payload) if isinstance(payload, dict) else {}
    section.update(
        ready=bool(gate.get("ready")), version_number=gate.get("version_number"),
        reason_codes=list(gate.get("reason_codes") or []), reasons=list(gate.get("reasons") or []),
        critical_open=gate.get("critical_open"),
        blockers=[{k: b.get(k) for k in ("id", "title", "priority", "status")}
                  for b in gate.get("blockers") or [] if isinstance(b, dict)],
        blockers_truncated=bool(gate.get("blockers_truncated")))
    return section


def _dfm_signals(results: Dict[str, NodeResult],
                 quarantined: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    quarantined = [] if quarantined is None else quarantined
    feedback = _section_state(results, "feedback")
    section: Dict[str, Any] = {"outcome": feedback["outcome"]}
    if feedback["outcome"] == "answered" and _incomplete(results, "feedback"):
        section.update(outcome="partial", reason=_incomplete(results, "feedback"))
    if feedback["outcome"] == "answered":
        payload = _data(results, "feedback")
        rows = _rows(payload)
        open_serious = [{**{k: r.get(k) for k in ("id", "number", "priority", "status", "ai_generated")},
                         "title": _clean(r.get("title"), f"feedback {r.get('number') or r.get('id')} title",
                                         quarantined)}
                        for r in rows if str(r.get("status") or "").lower() not in CLOSED_FEEDBACK
                        and str(r.get("priority") or "").lower() in SERIOUS]
        section["feedback"] = {"total": payload.get("total", len(rows)) if isinstance(payload, dict) else len(rows),
                               "open_high_or_critical": open_serious}
    else:
        section["feedback"] = feedback
    checklists = _section_state(results, "failed_checklists")
    if checklists["outcome"] == "answered":
        section["failed_checklists"] = [
            {k: r.get(k) for k in ("id", "number", "category", "overall_result", "checklist_id")}
            for r in _rows(_data(results, "failed_checklists"))]
    elif checklists["outcome"] == "not_run":
        section["failed_checklists"] = []
        section["failed_checklists_note"] = "not read: the release gate reported no blockers"
    else:
        section["failed_checklists"] = []
        section["failed_checklists_note"] = f"not available: {checklists.get('reason')}"
    standards = _section_state(results, "dfm_standards")
    if standards["outcome"] == "answered":
        data = _data(results, "dfm_standards") or {}
        section["standards"] = {
            "query": data.get("query"), "indexed_records": data.get("indexed_records"),
            "matches": [{k: m.get(k) for k in ("id", "name", "category", "standard_body", "standard_number",
                                                "is_active", "score", "matched_terms")}
                        for m in data.get("matches") or []],
            "note": "matched by keyword against DesignStandard names/descriptions; relevance, not compliance"}
    elif standards["outcome"] != "not_run":
        section["standards"] = standards
    return section


def _schedule(results: Dict[str, NodeResult], today: str) -> Dict[str, Any]:
    section = _section_state(results, "milestones")
    if section["outcome"] != "answered":
        return section
    rows = sorted(_rows(_data(results, "milestones")), key=lambda r: (r.get("due_date") or "", r.get("order") or 0))
    milestones = [milestone_view(r, today) for r in rows]
    open_ms = [m for m in milestones if str(m.get("status") or "").lower() not in ("completed", "skipped")]
    section.update(as_of=today, milestones=milestones,
                   past_due=[m["name"] for m in milestones if m["past_due"]],
                   next_open=next((m["name"] for m in open_ms if not m["past_due"]), None),
                   note="past_due = due date before as_of and not completed/skipped (computed; the platform "
                        "does not set 'overdue' itself)")
    return section


def _handoffs(results: Dict[str, NodeResult], dry_run: bool) -> Dict[str, Any]:
    section = _section_state(results, "cross_seat")
    if section["outcome"] != "answered":
        return section
    data = _data(results, "cross_seat") or {}
    proposed = data.get("handoffs") or []
    section.update(proposed=proposed, items_considered=data.get("items_considered"),
                   sources_unavailable=data.get("sources_unavailable") or [], filed=False, would_file=[])
    filing = results.get("file_handoffs")
    if filing is not None:
        payload = filing.data if isinstance(filing.data, dict) else {}
        section["would_file"] = payload.get("would_file") or []
        section["filed"] = bool(payload.get("filed")) and filing.verdict == RESOLVED and not dry_run
        section["filing"] = {"verdict": filing.verdict, "reason": filing.reason}
        if not dry_run:
            section.update(escalations=payload.get("escalations") or [],
                           already_open=payload.get("already_open") or [],
                           filing_errors=payload.get("errors") or [], assignee=payload.get("assignee"))
    if not proposed:
        section["note"] = "no open serious item needs another team"
    elif dry_run:
        section["note"] = "dry run: hand-offs are proposed, nothing was filed"
    elif section["filed"]:
        section["note"] = f"filed and assigned to {section.get('assignee')}"
    else:
        section["note"] = f"not filed: {(section.get('filing') or {}).get('reason')}"
    return section


def build_finding(results: Dict[str, NodeResult], params: Dict[str, Any], *, run_id: str = "",
                  dry_run: bool = True) -> Dict[str, Any]:
    prompt = params.get("prompt", "")
    declines = [{"node": node, "reason": r.reason, "error_kind": r.error_kind}
                for node, r in results.items() if r.verdict == DECLINED]
    finding: Dict[str, Any] = {
        "schema": FINDING_SCHEMA, "run_id": run_id, "dry_run": dry_run,
        "snapshot_at": now_utc().isoformat(timespec="seconds"),
        "question": prompt, "file_id": params.get("file_id"), "declines": declines,
    }
    file_state = _section_state(results, "design_file")
    if file_state["outcome"] != "answered":
        # The first refusal explains it (e.g. a needed tool is not in this seat);
        # otherwise the design file itself could not be read.
        why = next((d["reason"] for d in declines if d["node"] != "design_file"), None)
        finding.update(outcome="declined", file=None,
                       refusal=f"Cannot answer: {why}" if why else
                       f"Cannot answer: design file {params.get('file_id')} -- {file_state.get('reason')}")
        return finding

    raw = _data(results, "design_file") or {}
    finding["file"] = {k: raw.get(k) for k in FILE_KEYS}
    finding["file"]["project_id"] = raw.get("project_id")
    sections = []
    quarantined: List[Dict[str, str]] = []
    if "revisions" in results:
        finding["revision_delta"] = _revision_delta(results, prompt, quarantined)
        if finding["revision_delta"]["outcome"] == "answered" and _incomplete(results, "revisions"):
            finding["revision_delta"].update(outcome="partial", reason=_incomplete(results, "revisions"))
        sections.append(finding["revision_delta"])
    finding["release_gate"] = _release_gate(results)
    for b in finding["release_gate"].get("blockers") or []:
        b["title"] = _clean(b.get("title"), f"release blocker {b.get('id')} title", quarantined)
    finding["dfm_signals"] = _dfm_signals(results, quarantined)
    sections += [finding["release_gate"], finding["dfm_signals"]]
    if "milestones" in results:
        finding["schedule"] = _schedule(results, finding["snapshot_at"][:10])
        sections.append(finding["schedule"])
    if "cross_seat" in results:
        finding["handoffs"] = _handoffs(results, dry_run)
        if finding["handoffs"].get("outcome") == "answered" and _incomplete(results, "feedback"):
            # Hand-offs are decided from the open items; with some missing, "nobody else needs to act"
            # could be wrong, so none is proposed.
            finding["handoffs"] = {"outcome": "declined", "proposed": [],
                                   "reason": f"{_incomplete(results, 'feedback')}, so hand-offs can't be decided"}
        sections.append(finding["handoffs"])
    if quarantined:
        finding["quarantined"] = quarantined
    finding["outcome"] = "answered" if all(s["outcome"] == "answered" for s in sections) else "partial"
    return finding
