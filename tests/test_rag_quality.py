"""
Offline tests for retrieval *quality*, not just retrieval mechanics: recall@k and MRR on a small
hand-labelled set, a relevance floor, query expansion, a stable passage order, a chunking comparison and
context-carrying chunks (agentkit/retrieval/*, gather_dfm_standards in packs/designreview/actions.py).
Markers: none

Author(s): ____________    Written by hand: [ ] yes

Background: docs/RESEARCH_GAP_ANALYSIS.md, gaps I10, I11, I12, I14, I16, I17.
Items marked (not built yet) test a feature that does not exist today: write the test, and mark it
@pytest.mark.xfail(strict=True, reason="I#") (or skip) until the feature lands.

Use cases to cover:
  Metrics (I10) -- write the small helper in the test or wait for the product one:
  [ ] recall@k and MRR on a 3-query hand-made table: exact values
      (e.g. relevant at rank 1, rank 3, not found -> MRR = (1 + 1/3 + 0) / 3 = 4/9)
  [ ] on the captured Suryodaya standards, the t01 change notes recall "Sheet metal bend rules" within the
      top 5 (works today; note the captured standards are name-only, so each is one short passage)

  Relevance floor (I11, not built yet):
  [ ] a query that shares only one incidental word with a standard ("coffee machine warranty steel" vs
      a hot-rolled-steel bend rule) recalls nothing -- today it recalls the bend rule through "steel"
  [ ] scores map to correct / ambiguous / incorrect bands at the agreed thresholds

  Query expansion (I12, not built yet):
  [ ] a note that says "inside radius" recalls the "minimum bend radius" standard

  Stable order (I14):
  [ ] the same hits always come back in the same order (ties broken the same way every time)

  Chunking comparison (I16, not built yet):
  [ ] fixed 256 words, fixed 512 with overlap, header-aware, and header + topic chunking each give a
      recall@5 / MRR row; the cheapest within noise is the one used

  Context-carrying chunks (I17, not built yet):
  [ ] a child passage's indexed text starts with its parent's name and category; the text shown to
      the narrator does not

Hint: ParentChildIndex().add_documents([ParentDoc(id=..., text=..., meta=..., entity="DesignStandard")]),
then recall_parents(query, k=5). EvidenceIndex is the flat BM25 index; fixed_span_passages is the
fixed-size baseline; standards_query(results) builds the query the action uses.
"""

import pytest

from agentkit.retrieval import (EvidenceIndex, ParentChildIndex, ParentDoc, chunk_by_topic, fixed_span_passages,
                                section_children)
from packs.designreview.actions import standards_query

# Write your tests below.
