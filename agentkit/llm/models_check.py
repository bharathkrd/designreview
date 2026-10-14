"""
Is every configured LLM model still served? (a model-drift check)

    python -m agentkit.llm.models_check     # table; exit 1 if a configured model is gone

Providers retire models (one was retired 2026-08-26 while still configured in a .env). For each
provider that has a key, this reads the provider's own model list -- keys in headers only, never in
URLs -- and reports, per provider:
  ok           the configured model is listed
  RETIRED      the list came back and the model is not in it
  unknown      the list could not be read (network, auth, billing): says why; not a failure
Read-only, one GET per provider, no tokens spent. Not part of the offline CI (it needs keys and the
network); run it before a live batch.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from agentkit.llm.gateway import ANTHROPIC_VERSION, LLMGateway
from agentkit.transport.wire import refuse_if_offline

OPENAI_STYLE = {
    "groq": "https://api.groq.com/openai/v1/models",
    "cerebras": "https://api.cerebras.ai/v1/models",
    "nvidia": "https://integrate.api.nvidia.com/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
}


def _list_request(gw: LLMGateway, provider: str, key: str) -> Optional[Tuple[str, Dict[str, str]]]:
    if provider in OPENAI_STYLE:
        return OPENAI_STYLE[provider], {"Authorization": f"Bearer {key}"}
    if provider == "openai":
        base = gw._env.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        base = base[: -len("/chat/completions")] if base.endswith("/chat/completions") else base
        return f"{base}/models", {"Authorization": f"Bearer {key}"}
    if provider == "anthropic":
        return "https://api.anthropic.com/v1/models?limit=1000", {"x-api-key": key,
                                                                  "anthropic-version": ANTHROPIC_VERSION}
    if provider == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", {"x-goog-api-key": key}
    if provider == "ollama":
        return gw._env.get("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/tags", {}
    return None


def model_ids(payload: Any) -> List[str]:
    """Model ids from any of the providers' list shapes."""
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("models") or []
    out = []
    for r in rows:
        if isinstance(r, dict):
            name = r.get("id") or r.get("name") or r.get("model") or ""
            out.append(name[len("models/"):] if name.startswith("models/") else name)
    return out


def check(gw: Optional[LLMGateway] = None) -> List[Dict[str, str]]:
    gw = gw or LLMGateway()
    rows = []
    for provider in sorted(gw._adapters):
        key = gw._key(provider)
        if key is None:
            continue  # no key: not in use
        model = gw.model_for(provider)
        req = _list_request(gw, provider, key)
        if req is None or not model:
            rows.append({"provider": provider, "model": model, "status": "unknown", "detail": "no list endpoint"})
            continue
        url, headers = req
        try:
            if gw._real_network:
                refuse_if_offline("LLM model list")
            resp = gw._client.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            ids = model_ids(resp.json())
        except Exception as e:  # not readable: say why, don't guess
            rows.append({"provider": provider, "model": model, "status": "unknown",
                         "detail": gw._scrub(f"{type(e).__name__}: {e}")[:120]})
            continue
        listed = model in ids or f"{model}:latest" in ids
        rows.append({"provider": provider, "model": model, "status": "ok" if listed else "RETIRED",
                     "detail": f"{len(ids)} models listed"})
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    argparse.ArgumentParser(description="Check that every configured LLM model is still served.").parse_args(argv)
    from agentkit.config import load_env

    load_env()
    rows = check(LLMGateway(env=dict(os.environ)))
    print("| Provider | Model | Status | Detail |\n|---|---|---|---|")
    for r in rows:
        print(f"| {r['provider']} | {r['model']} | {r['status']} | {r['detail']} |")
    retired = [r for r in rows if r["status"] == "RETIRED"]
    print(f"\n{len(retired)} retired model(s) configured." if retired else "\nNo retired model configured.")
    return 1 if retired else 0


if __name__ == "__main__":
    sys.exit(main())
