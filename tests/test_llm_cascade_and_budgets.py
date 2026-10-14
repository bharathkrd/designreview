"""
Offline tests for how LLM calls are spent: an audit-gated cascade (cheap model first), prompt-cache
friendly prompts, agreement across sampled drafts, finding-path citations, retired-model detection, and
per-node / per-run budgets (agentkit/llm/*, agentkit/answer/*, agentkit/graph/engine.py).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Background: docs/RESEARCH_GAP_ANALYSIS.md, gaps I1, I2, I3, I4, I5, I8.
Most items test features that do not exist today: write the test, and mark it
@pytest.mark.xfail(strict=True, reason="I#") (or skip) until the feature lands.

Use cases to cover:
  Works today (the base the cascade builds on):
  [ ] compose_answer with a fake gateway whose first draft passes the audit -> exactly 1 LLM call,
      answer_source "llm"
  [ ] first draft invents "2.5 mm", second is clean -> exactly 2 calls, the rewrite prompt names "3.0 mm"
  [ ] the cost ledger adds up input and output tokens per provider and the summary cost matches
      the price table

  Audit-gated cascade (I1, built 2026-10-14: compose_answer(tiers=...)):
  [ ] the cheap tier's draft passes the audit -> the quality tier is never called
  [ ] the cheap draft fails the audit -> the quality tier is called; the template only if both fail
  [ ] the ledger shows which tier answered, so cost per passing answer can be reported

  Prompt caching (I2, built 2026-10-14: stable system prompt first; gateway ANTHROPIC_CACHE_MIN_CHARS):
  [ ] two narrations with different findings send byte-identical prefixes (system prompt + instructions);
      the finding comes after the cache breakpoint
  [ ] an Anthropic request with a long enough system prompt carries a cache_control block;
      a short one does not

  Sampled agreement (I3, not built yet; eval-time only):
  [ ] 3 drafts, 2 state the same release verdict -> agreement = 2/3

  Finding-path citations (I4, not built yet):
  [ ] a sentence tagged [revision_delta.change_notes[1]] whose number matches that path -> passes
  [ ] a tag to a path that is not in the finding, or whose value differs -> audit fails
  [ ] tags are removed from the text the user sees

  Model drift (I5, built 2026-10-14: agentkit.llm.models_check.check / model_ids):
  [ ] a provider model list (faked) that no longer has the configured model -> preflight reports it

  Budgets (I8, built 2026-10-14: registry.action(timeout_s=), config.llm_budget_usd, compose_answer(max_cost_usd=)):
  [ ] an action that sleeps past its timeout_s ends FAILED with the reason; the other branch still
      finishes (requires="settled")
  [ ] a run whose ledger passes max_cost_usd stops calling the LLM and answers with the template,
      recording why

Hint: the narrator only needs an object with call(prompt, **kw) -> str (or call_detailed). For the
gateway itself, use LLMGateway(<routing file>, transport=httpx.MockTransport(handler), sleep=list.append,
env={...}) and inspect the request bodies the handler receives.
"""

import pytest

from agentkit.answer import audit_narrative, compose_answer
from agentkit.llm.economics import CostLedger
from agentkit.llm.gateway import LLMGateway
from packs.designreview.claims import CLAIM_RULES

# Write your tests below.
