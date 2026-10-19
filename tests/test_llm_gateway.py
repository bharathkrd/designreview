"""
Offline tests for agentkit/llm (gateway + cost ledger).    Markers: none
(Add a separate test marked `gateway_live` for one real call if you want -- it costs a fraction of a cent.)

Author(s): ____________    Written by hand: [ ] yes

Use cases to cover:
  [ ] A provider with no API key is skipped; tier order from config/routing.toml is respected
  [ ] 429 / 503 / 529 are retried with backoff 0.5, 1, 2, 4, 4 ... s (capped) then the next provider is tried
  [ ] 400 / 404 go straight to the next provider (no retry)
  [ ] 401 / 402 / 403 cool the provider down so the next call skips it
  [ ] stop_reason is normalised: STOP/stop/end_turn -> end_turn; MAX_TOKENS/length -> max_tokens; SAFETY -> refusal
  [ ] A truncated (max_tokens) reply is returned but NOT cached; a refusal moves to the next provider
  [ ] The cache key includes json_mode, max_tokens and tier (changing any one is a cache miss)
  [ ] The Gemini key goes in the x-goog-api-key header, never the URL; keys never appear in error text
  [ ] Anthropic: no `temperature` for claude-opus-5 / sonnet-5 / haiku-5; text taken only from "text" blocks
  [ ] The ledger records provider-reported input/output tokens and prices input and output separately
  [ ] A routing file with rpm = 0, a tier naming an unknown provider, or a misspelt key is rejected
  [ ] strip_reasoning: "<think>x</think>Answer" -> "Answer"; an unclosed <think> leaves ""; a reply that is only
      reasoning moves to the next provider; the cached text has no <think>; reply.reasoning_chars is set
For rows configured by URL or by `api`, the per-row request settings and the tier order, see
test_llm_providers.py.
More use cases (added 2026-10-16, to write by hand):
  [ ] the same prompt twice: the second answer comes from the cache and the handler sees one request
  [ ] all providers fail: the error names each provider tried and its status, never a key
  [ ] a 200 reply with no text (empty choices / no candidates) moves to the next provider
Hint: LLMGateway(<routing.json in tmp_path>, transport=httpx.MockTransport(handler), sleep=list.append,
env={"GEMINI_API_KEY": "k"}) -- the handler returns httpx.Response(200, json={...}). No network.
"""

import httpx
import pytest

from agentkit.llm.economics import CostLedger
from agentkit.llm.gateway import LLMGateway

# Write your tests below.
