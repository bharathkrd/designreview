"""
Retrieval quality: measure it, gate it, and widen the query -- all small and explainable.

Metrics (over a hand-labelled set: for each query, the ids that SHOULD come back):
  recall_at_k      share of the relevant ids found in the top k
  precision_at_k   share of the top k (or of fewer, if fewer came back) that are relevant
  reciprocal_rank  1 / rank of the first relevant id (0 when none is found); its mean is MRR
  evaluate         the three, averaged over the set

Relevance gate (a light form of a "retrieval evaluator" that decides what to do with
what came back, instead of passing the top k on regardless):
  relevance_band   "correct" | "ambiguous" | "incorrect" for one hit, from its score
                   relative to the best hit and an absolute floor
  gate_hits        keep correct and ambiguous hits (with their band), drop incorrect ones

Query expansion:
  expand_query     append the terms a caller maps a phrase to ("inside radius" ->
                   "bend radius sheet metal"), so a lexical index can match a synonym
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

# ---------------------------------------------------------------- metrics


def recall_at_k(ranked: Sequence[str], relevant: Set[str], k: int) -> float:
    if not relevant:
        return 1.0 if not ranked[:k] else 0.0  # nothing should come back
    return len(set(ranked[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: Set[str], k: int) -> float:
    top = list(ranked[:k])
    if not top:
        return 1.0 if not relevant else 0.0
    return sum(1 for r in top if r in relevant) / len(top)


def reciprocal_rank(ranked: Sequence[str], relevant: Set[str]) -> float:
    for i, r in enumerate(ranked, 1):
        if r in relevant:
            return 1.0 / i
    return 1.0 if not relevant and not ranked else 0.0


def evaluate(results: Iterable[Tuple[Sequence[str], Set[str]]], k: int = 5) -> Dict[str, float]:
    """Mean recall@k, precision@k and MRR over (ranked ids, relevant ids) pairs."""
    rows = list(results)
    if not rows:
        return {"queries": 0, f"recall@{k}": 0.0, f"precision@{k}": 0.0, "mrr": 0.0}
    n = len(rows)
    return {"queries": n,
            f"recall@{k}": round(sum(recall_at_k(r, rel, k) for r, rel in rows) / n, 4),
            f"precision@{k}": round(sum(precision_at_k(r, rel, k) for r, rel in rows) / n, 4),
            "mrr": round(sum(reciprocal_rank(r, rel) for r, rel in rows) / n, 4)}


# ---------------------------------------------------------------- relevance gate


@dataclass(frozen=True)
class GateConfig:
    keep_ratio: float = 0.5        # >= this share of the best score: "correct"
    ambiguous_ratio: float = 0.3   # >= this share: "ambiguous"; below: "incorrect"
    min_score: float = 0.0         # an absolute floor under which nothing is kept


def relevance_band(score: float, best: float, cfg: GateConfig = GateConfig()) -> str:
    if score <= cfg.min_score or best <= 0:
        return "incorrect"
    share = score / best
    if share >= cfg.keep_ratio:
        return "correct"
    return "ambiguous" if share >= cfg.ambiguous_ratio else "incorrect"


def gate_hits(hits: Sequence[Any], cfg: GateConfig = GateConfig()) -> List[Tuple[Any, str]]:
    """(hit, band) for every hit that is not "incorrect", in the original order.
    A hit is anything with a numeric `.score`."""
    best = max((h.score for h in hits), default=0.0)
    banded = [(h, relevance_band(h.score, best, cfg)) for h in hits]
    return [(h, b) for h, b in banded if b != "incorrect"]


# ---------------------------------------------------------------- query expansion


def expand_query(query: str, synonyms: Mapping[str, Iterable[str]]) -> str:
    """The query plus the extra terms of every phrase in `synonyms` it contains
    (case-insensitive, whole words). The original text is kept first."""
    text = query or ""
    extra: List[str] = []
    for phrase, terms in (synonyms or {}).items():
        if re.search(r"\b" + re.escape(phrase.lower()) + r"\b", text.lower()):
            extra += [t for t in terms if t not in extra]
    return text + (" " + " ".join(extra) if extra else "")
