"""
Offline tests for agentkit/retrieval/hierarchy.py (split_by_headers, ParentChildIndex).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Use cases to cover:
  [ ] split_by_headers gives one passage per Markdown section with its header path
      ("# A" / "## B" / "### C" -> ["A", "B", "C"]; a new "## D" resets to ["A", "D"])
  [ ] a "#" line inside a ``` code fence is not a heading
  [ ] text[p.start_char:p.end_char] == p.text for every passage
  [ ] recall_parents returns the whole parent record although only one of its sections matched
  [ ] each parent appears once, in the rank order of its best child
  [ ] a removed parent is dropped from the results (its children are still indexed)
  [ ] distinct_by="family" keeps one parent per family; where={"category": ...} filters on inherited meta
  [ ] child_meta_fields=["category"] means children carry only that field (plus parent id and header path)
  [ ] adding two parents with the same id is an error
More use cases (added 2026-10-16, to write by hand):
  [ ] mget(["a", "missing"]) returns [<doc a>, None]
  [ ] split_by_headers(max_level=2): a "### C" line stays inside the "## B" passage
  [ ] strip_headers=True: passage text has no "#" line, and the offsets still slice the source exactly
Hint: ParentChildIndex(child_splitter=section_children(min_words=1000)) keeps each section as one child,
so the results are easy to predict.
"""

import pytest

from agentkit.retrieval import ParentChildIndex, ParentDoc, section_children, split_by_headers

# Write your tests below.
