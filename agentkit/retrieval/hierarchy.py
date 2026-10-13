"""
Search small, return whole: parent-child retrieval and header-path splitting.

split_by_headers(text)
    One passage per Markdown section. Each passage carries its header path
    (meta["header_path"] = ["Bending", "Minimum radius"]) and exact offsets.
    A '#' line inside a code fence is code, not a heading. With
    strip_headers=True the heading line itself is left out of the text.

ParentChildIndex
    Index small CHILD passages (precise keyword matches) but answer with the
    whole PARENT they came from (full context for the narrator). Each child
    stores its parent's id under `id_key`; recall_parents():
      1. BM25 over the children (agentkit.retrieval.index)
      2. parent ids taken in the children's rank order, each kept once
      3. parents looked up by id; an id whose parent is gone is dropped
    A parent's score is its best child's; `matched` is every query term any
    of its matching children hit; `children` are those hits, best first.
    Optional `parent_splitter` cuts a large document into mid-size parents
    first; the default child splitter is section_children (headers, then
    chunk_by_topic inside each section), so the rule that a model may only
    locate a topic boundary -- never write one -- still holds for children.

The two-level index (rank-order de-duplication, missing parents dropped) and
the header-stack splitting are adapted from an external open-source
retrieval design (referred to from outside sources); BM25 children and
verbatim-suffix chunking are ours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from agentkit.retrieval.chunker import EvidencePassage, _word_index, chunk_by_topic
from agentkit.retrieval.index import EvidenceIndex, Hit

_HEADER = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(```|~~~)")


def split_by_headers(text: str, *, max_level: int = 6, strip_headers: bool = False, source_id: str = "",
                     source_entity: str = "", meta: Optional[Dict[str, Any]] = None) -> List[EvidencePassage]:
    if not text or not text.strip():
        return []
    sections: List[Tuple[int, int, List[str], int]] = []  # (start, end, header path, level)
    stack: List[Tuple[int, str]] = []
    start, path, level = 0, [], 0
    fence: Optional[str] = None
    pos = 0
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        f = _FENCE.match(bare)
        if f:
            fence = None if fence == f.group(1) else (fence or f.group(1))
        m = _HEADER.match(bare) if fence is None and not f else None
        if m and len(m.group(1)) <= max_level:
            sections.append((start, pos, path, level))
            lvl = len(m.group(1))
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, m.group(2).strip()))
            path, level = [t for _, t in stack], lvl
            start = pos + len(line) if strip_headers else pos
        pos += len(line)
    sections.append((start, len(text), path, level))

    out: List[EvidencePassage] = []
    for s, e, hpath, lvl in sections:
        chunk = text[s:e]
        body = chunk.strip()
        if not body:
            continue
        s2 = s + chunk.find(body)
        e2 = s2 + len(body)
        out.append(EvidencePassage(text=body, ordinal=len(out), source_id=source_id, source_entity=source_entity,
                                   heading=hpath[-1] if hpath else None, start_char=s2, end_char=e2,
                                   start_word=_word_index(text, s2), end_word=_word_index(text, e2),
                                   boundary_note={"mode": "headers", "level": lvl},
                                   meta={**(meta or {}), "header_path": list(hpath)}))
    return out


@dataclass(frozen=True)
class ParentDoc:
    id: str
    text: str
    meta: Dict[str, Any] = field(default_factory=dict)
    entity: str = ""


@dataclass
class ParentHit:
    parent: ParentDoc
    score: float
    matched: List[str]
    children: List[Hit]


def section_children(word_budget: int = 512, min_words: int = 40, splitter: Any = None
                     ) -> Callable[[ParentDoc], List[EvidencePassage]]:
    """Child splitter: Markdown sections first, then topic chunks inside each
    section; every child keeps its section's header path."""

    def split(doc: ParentDoc) -> List[EvidencePassage]:
        out: List[EvidencePassage] = []
        for section in split_by_headers(doc.text, source_id=doc.id, source_entity=doc.entity):
            for p in chunk_by_topic(section.text, word_budget=word_budget, min_words=min_words, splitter=splitter,
                                    source_id=doc.id, source_entity=doc.entity, meta=section.meta):
                out.append(replace(p, ordinal=len(out), start_char=section.start_char + p.start_char,
                                   end_char=section.start_char + p.end_char,
                                   heading=p.heading or section.heading))
        return out

    return split


class ParentChildIndex:
    def __init__(self, child_splitter: Optional[Callable[[ParentDoc], List[EvidencePassage]]] = None,
                 parent_splitter: Optional[Callable[[ParentDoc], List[ParentDoc]]] = None,
                 id_key: str = "parent_id", child_meta_fields: Optional[Sequence[str]] = None,
                 index: Optional[EvidenceIndex] = None):
        self.child_splitter = child_splitter or section_children()
        self.parent_splitter = parent_splitter
        self.id_key = id_key
        self.child_meta_fields = None if child_meta_fields is None else tuple(child_meta_fields)
        self.index = index or EvidenceIndex()
        self.parents: Dict[str, ParentDoc] = {}

    def __len__(self) -> int:
        return len(self.parents)

    def add_documents(self, docs: Iterable[ParentDoc]) -> int:
        """Store each parent and index its children; returns children added."""
        added = 0
        for doc in docs:
            for parent in (self.parent_splitter(doc) if self.parent_splitter else [doc]):
                if parent.id in self.parents:
                    raise ValueError(f"duplicate parent id {parent.id!r}")
                self.parents[parent.id] = parent
                inherited = (dict(parent.meta) if self.child_meta_fields is None
                             else {k: parent.meta[k] for k in self.child_meta_fields if k in parent.meta})
                children = [replace(c, source_id=c.source_id or parent.id,
                                    source_entity=c.source_entity or parent.entity,
                                    meta={**inherited, **c.meta, self.id_key: parent.id})
                            for c in self.child_splitter(parent)]
                added += self.index.add(children)
        return added

    def mget(self, ids: Iterable[str]) -> List[Optional[ParentDoc]]:
        return [self.parents.get(i) for i in ids]

    def remove(self, parent_id: str) -> None:
        """Forget a parent; its children stay indexed but are dropped at recall."""
        self.parents.pop(parent_id, None)

    def recall_parents(self, query: str, k: int = 4, where: Optional[Dict[str, Any]] = None,
                       distinct_by: Optional[str] = None, child_k: Optional[int] = None) -> List[ParentHit]:
        hits = self.index.recall(query, k=child_k or max(len(self.index), 1), where=where)
        order: List[str] = []
        grouped: Dict[str, List[Hit]] = {}
        for h in hits:
            pid = h.passage.meta.get(self.id_key)
            if pid is None:
                continue
            if pid not in grouped:
                order.append(pid)
            grouped.setdefault(pid, []).append(h)
        out: List[ParentHit] = []
        seen: set = set()
        for pid, parent in zip(order, self.mget(order)):
            if parent is None:
                continue
            if distinct_by:
                value = parent.meta.get(distinct_by)
                key = str(value).strip().lower() if value is not None else f"\0{pid}"
                if key in seen:
                    continue
                seen.add(key)
            group = grouped[pid]
            matched: List[str] = []
            for h in group:
                matched += [t for t in h.matched if t not in matched]
            out.append(ParentHit(parent, group[0].score, matched, group))
            if len(out) >= k:
                break
        return out
