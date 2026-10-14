"""
Offline tests for the LLM provider rows in config/routing.toml: endpoints configured by URL, second rows on
the native Anthropic / Gemini APIs, per-row request settings, the tier order, the record of which model
answered, and how .env values reach a batch's child processes (agentkit/llm/gateway.py,
agentkit/llm/models_check.py, agentkit/answer/narrator.py, agentkit/config.py).    Markers: none

Author(s): ____________    Written by hand: [ ] yes

Background: docs/explainers/agentkit_llm.md and config.md; docs/CHANGES.md entries of 2026-10-14;
tests/MANUAL_TEST_LOG.md rows A-LIVE-05 to A-LIVE-10. All of these features exist today.

Use cases to cover:
  Rows configured by URL (ProviderSpec.url / url_env, chat_url):
  [ ] chat_url("https://api.deepseek.com") and chat_url("https://api.moonshot.ai/v1/") both end in
      "/chat/completions"; a full ".../chat/completions" URL is kept as it is
  [ ] a row with url = "https://api.deepseek.com" posts to that endpoint with "Authorization: Bearer <key>"
  [ ] url_env set in env overrides the row's url
  [ ] a keyless row (LM Studio) sends no Authorization header
  [ ] a row whose key variable is not set is not in available_providers(); the next row answers

  Second rows on a native API (ProviderSpec.api = "anthropic" | "gemini"):
  [ ] a row named "anthropic_haiku" with api = "anthropic" posts to api.anthropic.com, and the reply's
      provider is "anthropic_haiku" (not "anthropic")
  [ ] a row with api = "gemini" posts to .../models/<model>:generateContent with the x-goog-api-key header
  [ ] the two Anthropic rows cool down separately: a 529 on the Haiku row does not stop the Sonnet row
  [ ] api = "cohere" (not a known API) -> load_routing raises a config error that names "api"

  Request settings for each row:
  [ ] temperature = 1 on a row replaces the caller's 0.1 in the request body; a row without it keeps 0.1
  [ ] max_tokens_field = "max_completion_tokens" sends that key and no "max_tokens"
  [ ] reasoning_effort = "low" is sent as is; a row without it sends no reasoning_effort
  [ ] a Claude 5.x model (claude-haiku-5-5, claude-sonnet-5-5) gets no "temperature" in the body

  The shipped tier order (config/routing.toml):
  [ ] fast starts openai_luna, deepseek_flash, moonshot, gemini_lite, anthropic_haiku
  [ ] quality and default start openai_sol, deepseek, moonshot, gemini, anthropic
  [ ] lmstudio, then ollama, are the last two rows of each tier

  Which model answered:
  [ ] compose_answer with a fake gateway whose call_detailed returns
      LLMReply("...", "deepseek_flash", "deepseek-flash", "end_turn", 10, 3) -> the result has
      provider "deepseek_flash" and model "deepseek-flash", and so does its first attempt
  [ ] models_check.check(gateway) on a faked model list without the configured model -> status "RETIRED"

  .env values in child processes (agentkit.config, AGENTKIT_DOTENV_KEYS):
  [ ] after load_env(<tmp .env with OPENAI_API_KEY>), from_process("OPENAI_API_KEY") is None
  [ ] simulate a child: keep os.environ, clear config._FROM_DOTENV, call load_env() again ->
      from_process("OPENAI_API_KEY") is still None, and candidate_order("default") does not start with "openai"
  [ ] a different value in the process (a runner-injected key) -> from_process gives it, and "openai" is first

Hint: build a routing file in tmp_path (JSON is accepted) and use
LLMGateway(<file>, transport=httpx.MockTransport(handler), sleep=lambda s: None, env={...}); read the
request bodies with json.loads(request.content). For the .env cases, use monkeypatch to set
agentkit.config._FROM_DOTENV to {} and to delete the variables, and remove AGENTKIT_DOTENV_KEYS after the test.
"""

import json

import httpx
import pytest

import agentkit.config as config
from agentkit.answer import compose_answer
from agentkit.answer.claim_audit import ClaimRules
from agentkit.config import from_process, load_env
from agentkit.llm.gateway import ROUTING_PATH, LLMGateway, LLMReply, chat_url, load_routing
from agentkit.llm.models_check import check

# Write your tests below.
