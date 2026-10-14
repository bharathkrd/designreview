"""
Routing a bare question for the design-review seat: which plan, which design file.

The routes are data (routes.toml). The resolver finds the design file the question names:

1. A record id (UUID) in the question is taken as the file id -- no search.
2. Otherwise every DesignFile is read (paged, journaled) and scored by the words of its
   name that occur in the question, each weighted log(N / df) (df = how many file names
   carry the word: a rare word says more). Words in more than max(DISTINCT_DF, 5% of N)
   names don't count: seed data repeats department words ("Quality", "Despatch") across
   many files, and those must not be evidence. Files within TIE of the best score tie.
3. When the question names revisions, only files with two or more versions qualify.
4. A tie with revisions named: each candidate's version notes are read; files whose own
   notes carry those revision letters are kept (a person would do the same).
5. Still more than one, or none: Declined, naming the candidates -- never a guess.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Sequence

from agentkit.agents.router import Declined, RuleRouter
from agentkit.config import read_config
from agentkit.transport import SeatCallFailure
from agentkit.transport.safe_reads import read_all
from packs.designreview.actions import SAFE_SERVER_FILTERS
from packs.designreview.finding import rev_letter, requested_pair, requested_revs

ROUTES_TOML = Path(__file__).parent / "routes.toml"
DISTINCT_DF = 3
TIE = 0.9  # a candidate within 10% of the best score is as good as the best
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_STOP = frozenset("the of and a an for on in to is are be it this that what which who with from by".split())


def words(text: str) -> List[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if w in _STOP or (len(w) < 2 and not w.isdigit()):
            continue
        out.append(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def _revs(prompt: str) -> List[str]:
    return requested_pair(prompt) or requested_revs(prompt)


def _label(row: Dict[str, Any]) -> str:
    return f"{row.get('number')} {row.get('name')}"


def _notes_name(client: Any, row: Dict[str, Any], revs: Sequence[str]) -> bool:
    """Do this file's own version notes carry every revision letter asked about?"""
    try:
        versions = read_all(client, "DesignVersion.list", {"file_id": row["id"]}, safe_keys=SAFE_SERVER_FILTERS)["data"]
    except SeatCallFailure:
        return False  # unreadable: not confirmed
    present = {rev_letter(v.get("commit_message") or "") for v in versions}
    return all(r in present for r in revs)


def resolve_design_file(client: Any, prompt: str, needs: Sequence[str]) -> Dict[str, Any]:
    if "file_id" not in needs:
        return {}
    m = _UUID.search(prompt or "")
    if m:
        return {"file_id": m.group(0)}
    rows = read_all(client, "DesignFile.list", {}, safe_keys=SAFE_SERVER_FILTERS)["data"]
    n = max(len(rows), 1)
    df = Counter(w for r in rows for w in set(words(r.get("name") or "")))
    limit = max(DISTINCT_DF, 0.05 * n)
    asked = set(words(prompt))
    scored = []
    for r in rows:
        shared = {w for w in set(words(r.get("name") or "")) if df[w] <= limit} & asked
        scored.append((sum(math.log(n / df[w]) for w in shared) if n > 1 else float(len(shared)), r))
    best = max((s for s, _ in scored), default=0.0)
    if best <= 0:
        raise Declined("no design file's name matches the question")
    top = [r for s, r in scored if s >= TIE * best]
    revs = _revs(prompt)
    if revs:
        top = [r for r in top if (r.get("current_version") or 0) >= 2] or top
        if len(top) > 1:
            top = [r for r in top if _notes_name(client, r, revs)] or top
    if len(top) > 1:
        raise Declined(f"ambiguous: the question could mean {len(top)} design files ("
                       + "; ".join(_label(r) for r in top[:5]) + ") -- name the part number")
    return {"file_id": top[0]["id"]}


def make_router(path: Path = ROUTES_TOML) -> RuleRouter:
    return RuleRouter.from_config(read_config(path), resolve_design_file)
