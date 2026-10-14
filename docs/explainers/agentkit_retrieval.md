# `agentkit/retrieval/` — chunking and recall

*Reading order: **5th**. Files: `chunker.py`, `index.py`, `hierarchy.py`, `quality.py`. The action
`gather_dfm_standards` of the pack uses this module. Written in ASD-STE100 (Simplified Technical English)
style, 2026-10-14.*

## Overview

- `chunk_by_topic()` divides long text into topic passages. An LLM cannot invent a boundary.
- `EvidenceIndex` is a BM25 keyword index on those passages. It uses only the standard library.
- `ParentChildIndex` searches small passages and gives the full record.
- `quality.py` measures the retrieval on labelled queries.

## Design decisions

### Chunking

- **The model finds a boundary. It never writes one.** The chunker cuts text into blocks of 512 words or
  fewer. It never cuts inside a Markdown heading, an open code fence or a table.
- **The verbatim-suffix rule.** A splitter says where a
  second topic starts. The chunker accepts the answer **only if it is a verbatim suffix of the block**. That
  suffix then goes into the next block.
- **A bad splitter answer changes nothing.** If the answer is a paraphrase or an invention, the chunker
  rejects it and keeps the block as one passage. If the splitter fails, the chunker records the failure. It
  does not record "one topic".
- **You can trace each passage.** Each passage records how the chunker found its boundary (`boundary_note`).
  It also has its exact character and word offsets in the source.
- **Short text costs nothing.** A text of fewer than `min_words` (40) words is one passage, and the chunker
  does not call the splitter. Each `DesignStandard` record today has 4 to 28 words.

### The index

- **BM25, no embeddings.** There are few records, and they are short. The index is made again on each run.
  Thus an embedding model or a vector store adds a dependency and gives no improvement.
- **Each hit shows the terms that matched.** A query term that occurs more than one time has more weight.
- **Duplicates collapse.** `distinct_by` keeps one record for each value. The seed data repeats the names of
  standards in many departments. On a tie, the record with the lower `meta["_rank"]` stays. The pack uses
  this to prefer active records.

### Search small, return the full record (since 2026-10-13, `hierarchy.py`)

Before, a hit was the passage that matched. Now `ParentChildIndex` indexes small *children* for exact
matches, but it gives the full *parent* record:

1. BM25 searches the children.
2. The index takes the parent ids in the rank sequence of the children. Each parent occurs one time.
3. The index finds each parent by its id. If a parent is gone, the index drops it.

The score of a parent is the score of its best child. `children` lists the children that matched.

The default child splitter is `section_children`:

1. It cuts by Markdown section first (`split_by_headers`). Each child keeps its header path, for example
   `["Bending", "Aluminium"]`. A `#` line inside a code fence is code, not a header.
2. Then it runs `chunk_by_topic` in each section. Thus the verbatim-suffix rule still decides each boundary.

The optional `parent_splitter` makes parents of medium size from a very large document.

Today each standard is one short record, so one child is the full parent. The results are the same as
before, and the offline tasks show this. The improvement comes when records have clauses: the narrator gets
the full standard, and the match names the clause.

*The index with two levels and the header-stack splitting come from an external open-source retrieval
design. The BM25 children and the verbatim-suffix chunking are original to this project.*

## Retrieval quality (since 2026-10-14)

- **Measured, not assumed.** `quality.py` has `recall_at_k`, `precision_at_k`, `reciprocal_rank` and
  `evaluate`. `evaluate` gives the means over a labelled set.
- **Labelled queries.** The design-review pack keeps 4 hand-labelled queries in
  `packs/designreview/retrieval.toml`.
- **The evaluation script.** `python scripts/retrieval_eval.py` shows recall@5, precision@5 and MRR in four
  configurations: BM25 alone, each of the three aids alone, and all three aids together.
- **A CI floor.** `scripts/retrieval_eval.py --check` is a CI step. It fails if the configuration of the agent
  goes below the `[floors]` in the file.
- **A relevance gate.** `gate_hits(hits, GateConfig(keep_ratio, ambiguous_ratio, min_score))` compares each
  hit with the best hit. It puts each hit in one of three bands: correct, ambiguous or dropped. The action
  gives the band. The answer marks an ambiguous standard as "possibly relevant".
- **Query expansion.** `expand_query(query, synonyms)` adds the terms of each phrase that it finds. It
  matches whole words, and it ignores case.
- **Chunks that carry context.** `ParentChildIndex(context_keys=...)` puts those meta values of the parent in
  `meta["index_prefix"]` of each child. `EvidenceIndex` searches the prefix and the text, but it shows only
  the text.
- **The results on 2026-10-14.** Recall@5 stayed at 1.00. Precision@5 went from 0.72 to 0.88. MRR stayed at
  1.00. No aid alone made the precision better. The three aids together did.

## In the design-review pack

1. `gather_dfm_standards` reads each `DesignStandard` page through the journaled client.
2. It makes each record a parent (name and description) in a `ParentChildIndex`.
3. It makes the query from the change notes and the release blockers, and adds the synonyms.
4. It searches, and the relevance gate puts each hit in a band.
5. Each match has `section` (the header path of the child that matched) and up to 300 characters of the full
   record.

The finding gives the matches the label "relevance, not compliance". On the live platform, "Sheet metal bend
rules" is first for the Battery Tray.

## Key types

| Name | Purpose |
|---|---|
| `EvidencePassage` | Text, ordinal, source id and entity, heading, offsets, `boundary_note`, meta. |
| `TopicSplitter` protocol, `GatewayTopicSplitter`, `HeadingSplitter` | The source of the boundary. |
| `chunk_by_topic(text, word_budget=512, min_words=40, splitter=, source_id=, meta=)` | The chunker. |
| `fixed_span_passages()` | A fixed-window baseline for comparison. |
| `EvidenceIndex.add()`, `.recall(query, k, where=, distinct_by=)` | Index and search. |
| `split_by_headers(text, max_level=, strip_headers=)` | One passage for each Markdown section, with `meta["header_path"]`. |
| `ParentDoc`, `ParentChildIndex(child_splitter=, parent_splitter=, id_key=, child_meta_fields=, context_keys=)` | Search children, give parents: `.add_documents()`, `.recall_parents(query, k, where=, distinct_by=)`, `.mget()`, `.remove()`. |
| `recall_at_k`, `precision_at_k`, `reciprocal_rank`, `evaluate` | The quality metrics. |
| `GateConfig`, `gate_hits`, `expand_query` | The relevance gate and the query expansion. |
| `plain_text(html)` | Changes platform HTML descriptions into clean lines. |

## How to test

1. The hand-written templates are `tests/test_retrieval.py` and `tests/test_rag_quality.py`.
2. A scripted splitter is any object with `trailing_topic(block)`.
3. Run `python scripts/retrieval_eval.py --check` for the floors.
