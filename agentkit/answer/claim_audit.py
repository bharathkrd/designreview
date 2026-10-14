"""
audit_narrative(): does an answer say only what the finding says, and enough of it?

Deterministic, no LLM. Four kinds of problem:

- unsupported_ids         a record UUID in the text that appears nowhere in the finding
- unsupported_quantities  a number-with-unit (per the pack's pattern) whose value matches
                          no number anywhere in the finding (numbers inside finding
                          strings count -- e.g. "2.0 mm" inside a commit message)
- contradictions          pack-defined: the text asserts the opposite of the finding
                          (e.g. "ready for release" when the gate says not ready)
- missing                 pack-defined facts the answer must carry but left out

The pack supplies a ClaimRules (what a quantity looks like, which facts are
required, which contradictions to look for); this module holds no domain
vocabulary.

correction_note() is what the model gets back for its one rewrite. Given the
finding it is grounded: for each unsupported quantity it names the closest
verified values and where they sit in the FINDING ("'2.5 mm' is not in the
FINDING; verified: '3.0 mm' at revision_delta.change_notes[1]"), so the
rewrite has the right value to use instead of only being told what to drop.
A pack can add its own lines through ClaimRules.explain(report, finding).
(Self-correction works when the feedback comes from an outside check and
says what is right, not only what is wrong; see docs/explainers/agentkit_answer.md.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, Tuple

UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
# Every number found in the finding (including inside strings) widens what the
# text may cite, so a simple, permissive pattern is the safe choice here.
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
# ...except dates, clock times and UUIDs: "12" in a 12:05 snapshot time is not
# evidence for "12 mm", so these are removed before numbers are collected.
NOT_A_QUANTITY_RE = re.compile(
    UUID_RE.pattern + r"|\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"|\b\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\b", re.I)
TOLERANCE = 1e-6

# Optional citations in the prose: "[@revision_delta.change_notes[0]]" after a sentence names the finding
# path its facts come from. The audit checks each one; strip_citations() removes them for display.
CITATION_RE = re.compile(r"\s?\[@((?:[A-Za-z_]\w*|\[\d+\])(?:\.[A-Za-z_]\w*|\[\d+\])*)\]")
_PATH_PART = re.compile(r"\.?([A-Za-z_]\w*)|\[(\d+)\]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)")
_MISSING = object()


@dataclass
class RequiredFact:
    label: str  # human wording used in the correction note
    patterns: List[str]  # regexes; the fact is present if ANY matches (case-insensitive)

    def present_in(self, text: str) -> bool:
        return any(re.search(p, text, re.I) for p in self.patterns)


@dataclass
class ClaimRules:
    quantity_re: Optional[Pattern[str]] = None  # group 1 = numeric value
    required: Callable[[Dict[str, Any]], List[RequiredFact]] = lambda finding: []
    contradictions: Callable[[str, Dict[str, Any]], List[str]] = lambda text, finding: []
    ignore_ids: Set[str] = field(default_factory=set)
    # Extra correction lines: explain(report, finding) -> [str]
    explain: Optional[Callable[[Dict[str, Any], Dict[str, Any]], List[str]]] = None


def known_numbers(obj: Any, out: Optional[Set[float]] = None) -> Set[float]:
    out = set() if out is None else out
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        for m in NUMBER_RE.findall(NOT_A_QUANTITY_RE.sub(" ", obj)):
            try:
                out.add(float(m))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            known_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            known_numbers(v, out)
    return out


def _flat(obj: Any) -> str:
    return repr(obj).lower()


def strip_citations(text: str) -> str:
    """The text a reader sees: every "[@path]" citation removed."""
    return CITATION_RE.sub("", text or "")


def resolve_path(finding: Any, path: str) -> Any:
    """The value at a finding path such as "revision_delta.change_notes[1]"; _MISSING if there is none."""
    node, pos = finding, 0
    for m in _PATH_PART.finditer(path):
        if m.start() != pos:
            return _MISSING
        pos = m.end()
        key, index = m.group(1), m.group(2)
        if key is not None:
            if not isinstance(node, dict) or key not in node:
                return _MISSING
            node = node[key]
        else:
            i = int(index)
            if not isinstance(node, (list, tuple)) or i >= len(node):
                return _MISSING
            node = node[i]
    return node if pos == len(path) else _MISSING


def check_citations(text: str, finding: Dict[str, Any], rules: ClaimRules) -> Tuple[int, List[str]]:
    """(citations found, problems). A citation must name a path in the finding, and each quantity of the
    sentence it ends must be a number of the value(s) that sentence cites."""
    count, problems = 0, []
    for sentence in _SENTENCE_END.split(text or ""):
        paths = [m.group(1) for m in CITATION_RE.finditer(sentence)]
        if not paths:
            continue
        count += len(paths)
        cited: Set[float] = set()
        for path in paths:
            value = resolve_path(finding, path)
            if value is _MISSING:
                problems.append(f"[@{path}] is not a path in the FINDING")
            else:
                known_numbers(value, cited)
        if rules.quantity_re is None:
            continue
        for m in rules.quantity_re.finditer(strip_citations(sentence)):
            try:
                v = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if not any(abs(v - k) <= TOLERANCE for k in cited):
                problems.append(f"'{m.group(0).strip()}' is not in the value at "
                                + ", ".join(f"[@{p}]" for p in paths))
    return count, problems


def audit_narrative(text: str, finding: Dict[str, Any], rules: ClaimRules) -> Dict[str, Any]:
    raw = text or ""
    citations, bad_citations = check_citations(raw, finding, rules)
    text = strip_citations(raw)  # the other checks read what the reader will see
    flat = _flat(finding)
    numbers = known_numbers(finding)

    unsupported_ids = sorted({u for u in UUID_RE.findall(text)
                              if u.lower() not in flat and u.lower() not in rules.ignore_ids})
    unsupported_quantities: List[str] = []
    if rules.quantity_re is not None:
        for m in rules.quantity_re.finditer(text):
            try:
                value = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if not any(abs(value - k) <= TOLERANCE for k in numbers):
                unsupported_quantities.append(m.group(0).strip())
    contradictions = list(rules.contradictions(text, finding))
    missing = [f.label for f in rules.required(finding) if not f.present_in(text)]

    ok = not (unsupported_ids or unsupported_quantities or contradictions or missing or bad_citations)
    return {"ok": ok, "unsupported_ids": unsupported_ids,
            "unsupported_quantities": sorted(set(unsupported_quantities)),
            "contradictions": contradictions, "missing": missing,
            "citations": citations, "bad_citations": bad_citations}


def finding_quantities(finding: Any, rules: ClaimRules) -> List[Tuple[str, str, float]]:
    """Every quantity the finding states, as (path, text, value): quantities
    with a unit found inside its strings (rules.quantity_re), then plain
    numeric fields (text = the number)."""
    with_unit: List[Tuple[str, str, float]] = []
    plain: List[Tuple[str, str, float]] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str) and rules.quantity_re is not None:
            for m in rules.quantity_re.finditer(obj):
                try:
                    with_unit.append((path, m.group(0).strip(), float(m.group(1))))
                except (TypeError, ValueError):
                    continue
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            plain.append((path, str(obj), float(obj)))

    walk(finding, "")
    return with_unit + plain


def _unit(text: str, rules: ClaimRules) -> str:
    m = rules.quantity_re.search(text) if rules.quantity_re is not None else None
    return text[m.end(1):].strip().lower() if m else ""


def nearest_verified(quantity: str, finding: Any, rules: ClaimRules, limit: int = 2) -> List[Tuple[str, str]]:
    """The finding's closest quantities to an unsupported one, as (text, path):
    same unit first, then nearest value; each distinct text once."""
    m = rules.quantity_re.search(quantity) if rules.quantity_re is not None else None
    if not m:
        return []
    try:
        value = float(m.group(1))
    except (TypeError, ValueError):
        return []
    unit = _unit(quantity, rules)
    ranked = sorted(finding_quantities(finding, rules),
                    key=lambda q: (_unit(q[1], rules) != unit if unit else False, abs(q[2] - value), q[0]))
    out: List[Tuple[str, str]] = []
    for path, text, _ in ranked:
        if text not in {t for t, _ in out}:
            out.append((text, path))
        if len(out) >= limit:
            break
    return out


def correction_note(report: Dict[str, Any], finding: Optional[Dict[str, Any]] = None,
                    rules: Optional[ClaimRules] = None) -> str:
    """The message sent back to the LLM for its one rewrite. With the finding
    and rules, each unsupported quantity comes with the verified values to use."""
    lines = ["Your answer does not match the FINDING. Rewrite the whole answer from scratch, "
             "using only facts in the FINDING, and do not mention that it was corrected."]
    if report["unsupported_ids"]:
        lines.append("- These record ids are not in the FINDING; remove them: " + ", ".join(report["unsupported_ids"]))
    grounded = finding is not None and rules is not None and rules.quantity_re is not None
    if report["unsupported_quantities"] and not grounded:
        lines.append("- These quantities are not in the FINDING; remove them or use the FINDING's exact values: "
                     + ", ".join(report["unsupported_quantities"]))
    elif report["unsupported_quantities"]:
        for q in report["unsupported_quantities"]:
            near = nearest_verified(q, finding, rules)
            lines.append(f"- '{q}' is not in the FINDING; remove it"
                         + ("" if not near else ", or use a verified value: "
                            + ", ".join(f"'{t}' (at {p})" for t, p in near)) + ".")
    for c in report["contradictions"]:
        lines.append(f"- Contradicts the FINDING: {c}")
    if report["missing"]:
        lines.append("- You must also state: " + "; ".join(report["missing"]) + ".")
    for c in report.get("bad_citations") or []:
        lines.append(f"- Wrong citation: {c}. Cite the FINDING path that holds the fact, or remove the citation.")
    if finding is not None and rules is not None and rules.explain is not None:
        lines += [f"- {x}" for x in rules.explain(report, finding) if x]
    return "\n".join(lines)
