"""
build_tree(spans) -> the run tree: roots, each with nested "children".

Children are ordered by dotted_order (equivalently: by start time, since a
child's start is clamped to its parent's). A span whose parent isn't in the
list becomes a root rather than being dropped.

Provenance: adapted from an external open-source tracing design (run trees
ordered by a dotted path of start-time + id segments), referred to from
outside sources and rebuilt here in plain Python.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _order(node: Dict[str, Any]) -> tuple:
    return (node.get("start_ms") or 0.0, node.get("dotted_order") or "")


def build_tree(spans: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes = {s["span_id"]: {**s, "children": []} for s in spans}
    roots: List[Dict[str, Any]] = []
    for node in nodes.values():
        parent = nodes.get(node.get("parent_id")) if node.get("parent_id") else None
        (parent["children"] if parent is not None else roots).append(node)
    for node in nodes.values():
        node["children"].sort(key=_order)
    roots.sort(key=_order)
    return roots


def walk(tree: List[Dict[str, Any]], depth: int = 0) -> Iterable[tuple]:
    """(depth, node) for every node, parents before children."""
    for node in tree:
        yield depth, node
        yield from walk(node["children"], depth + 1)
