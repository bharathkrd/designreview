# `agentkit/answer/` — words checked against facts

*Reading order: **4th**. Files: `claim_audit.py`, `narrator.py`, `quarantine.py`. The design-review rules are
in `packs/designreview/claims.py` and `templates.py`. Written in ASD-STE100 (Simplified Technical English)
style, 2026-10-14.*

## Overview

Code calculates the finding before an LLM starts. The finding is the answer that the harness grades. The LLM
only writes the finding as text. The claim audit then compares that text with the finding. The agent never
gives LLM text that the audit did not accept.

## Design decisions

- **A deterministic audit.** `audit_narrative(text, finding, rules)` gives four lists of problems:
  - `unsupported_ids`: a UUID that is not in the finding;
  - `unsupported_quantities`: a number with a unit whose value is not in the finding (the digits of dates,
    clock times and UUIDs do not count);
  - `contradictions`: statements that the pack's rules reject;
  - `missing`: necessary facts that the text does not state.

  No LLM grades another LLM here.
- **The pack sets the rules.** The pack gives `ClaimRules(quantity_re, required, contradictions)`. This
  module has no domain words.
- **The first prompt lists the facts.** Thus most first drafts pass the audit.
- **A grounded rewrite.** A draft that fails gets a correction note. For each unsupported quantity, the note
  gives the nearest verified values and their paths in the finding. An example:
  `'2.5 mm' is not in the FINDING; remove it, or use a verified value: '2.0 mm' (at
  revision_delta.change_notes[0])`.
- **Why the rewrite gets the verified values.** Research shows that a model seldom corrects itself without outside
  feedback. It does better when an outside check says what is correct (Huang et al. 2023; Shinn et al.
  2023, Reflexion). A pack can add lines with `ClaimRules.explain(report, finding)`.
- **Platform text is data, not instructions.** The prompt puts the finding between
  `<untrusted_platform_data>` tags. A copy of that tag inside the data gets its `<` written as `<`. Thus
  the data cannot close the fence.
- **A data rule in each system prompt.** The system prompt always ends with `DATA_RULE`. That rule tells the model
  to use the data only as facts and never to obey instructions in it. If the model obeys them, the claim
  audit finds the contradiction, and the template gives the answer. (Greshake et al. 2023; Debenedetti et al.
  2025, CaMeL.)
- **Instruction-like text goes into quarantine.** `quarantine.py` finds instruction-like text in platform data,
  for example `SYSTEM:` or "ignore the rules". It cuts the sentence where the
  instruction starts. The finding records where it cut, and how many words.
- **There is always an answer.** The pack's template gives the answer in these conditions:
  - the rewrite also fails the audit;
  - no LLM provider is available;
  - the reply was cut off (`stop_reason = max_tokens`) in the last tier;
  - the run reached its LLM cost limit.

## The audit-gated cascade

`compose_answer(..., tiers=("fast", "quality"))` runs the narration:

1. The first tier (fast) writes one draft.
2. If the audit accepts the draft, it is the answer.
3. If the audit rejects it, or the draft was cut off, the next tier gets the prompt and the correction note.
4. The last tier can write one draft and one rewrite.
5. If no draft passes, the template gives the answer.

The loop skips a tier that has no available provider. Before each call, `compose_answer` compares the money that the
ledger spent with `max_cost_usd`.

## What the run records

`compose_answer` gives `text`, `source` (`"llm"` or `"template"`), `tier`, `provider`, `model`,
`fallback_reason`, `attempts` and `audit`. Each attempt has its `tier`, `provider`, `model` and audit.

The narrate step in `taskrun.json` keeps all of these, except the text of the attempts. Thus each run shows
the provider and the model that wrote the answer. The `llm_ledger.json` file also shows each call.

## The design-review rules (`packs/designreview/claims.py`)

- **Quantities.** A number with mm, °, kg, g or % must be in the finding.
- **Necessary facts.**
  - the release verdict (ready or NOT ready);
  - the number of open critical items;
  - each quantity in the compared change notes;
  - a statement that the change comes from the commit messages, not from a geometry comparison;
  - for a refusal: that the agent cannot answer the question, and the reason.
- **Contradictions.** The audit checks each sentence. It knows negation ("not ready").
  - "ready for release" when the gate is not ready, and the opposite;
  - a statement that a geometry comparison was done;
  - a standard (ISO, ASME, DIN, EN, ...) that is not in the finding. The prefixes are case-sensitive, so
    "rev B is v2" does not read as "IS v2".

## Key functions

| Function | Purpose |
|---|---|
| `audit_narrative(text, finding, rules) -> dict` | `ok` and the four lists of problems. |
| `correction_note(report, finding=None, rules=None) -> str` | The rewrite instruction. With the finding, it also gives the verified values. |
| `nearest_verified(quantity, finding, rules)`, `finding_quantities(finding, rules)` | The quantities of the finding, with their paths. |
| `fence_data(payload)`, `DATA_RULE`, `DATA_TAG` | The fence for untrusted data. |
| `quarantine_instructions(text)`, `looks_like_instruction(text)` | The quarantine for instruction-like text. |
| `compose_answer(query, finding, gateway=, rules=, template=, system_prompt=, instructions=, tiers=, max_cost_usd=)` | The narration loop, with the cascade and the cost limit. |
| `known_numbers(obj)` | Each number in the finding. Dates, times and UUIDs do not count, so a 12:05 time does not support "12 mm". |

## How to test

The hand-written template is `tests/test_finding_and_claims.py`. Make a finding from hand-made `NodeResult`
objects. Use a fake gateway whose `call_detailed()` gives scripted replies.
