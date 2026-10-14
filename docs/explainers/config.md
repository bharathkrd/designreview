# `config/` and `agentkit/config.py` — configuration

*Reading order: **0th** (skim). Written in ASD-STE100 (Simplified Technical English) style, 2026-10-14.*

## Overview

All configuration is TOML or JSON. The standard library (`tomllib`) reads the TOML files. Pydantic models
validate them.

| File | Model | Contents |
|---|---|---|
| `config/tenants.toml` | `TenantsConfig`, `TenantSpec` | For each tenant: the label, the URL variable, the default URL and the password variable. Names only, never values. |
| `config/routing.toml` | `RoutingConfig`, `ProviderSpec` | The LLM providers and the tiers. See `agentkit_llm.md` for each setting. |
| `config/project.toml` | — | `default_pack`, `default_tenant`, `max_llm_cost_usd_per_run`. |
| `packs/*/plans/*.toml` | `PlanModel` | Nodes and rules. See `agentkit_graph.md`. |
| `packs/*/tasks/*.toml` | `TaskDef` | Harness tasks. See `agentkit_harness.md`. |
| `packs/*/fixtures/*.json` | `SeatFixture` | Captured platform exchanges. |

## Design decision: pydantic at the boundary

People edit these files. A typing error must stop the program and show the exact field path. An example is
`nodes.0.tool: Extra inputs are not permitted`. The program must not ignore the error.

Internal runtime objects (graph nodes, results, run records) are plain dataclasses. They do not come from
people, so they do not need this check.

## `.env`

Git ignores `.env`. It has the values:

- the platform login: `AS_EMAIL`, `AS_SURYODAYA_PASSWORD`, `AS_KEYSTONE_PASSWORD`;
- the provider keys: `OPENAI_API_KEY2`, `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`, `GEMINI_API_KEY_2`,
  `ANTHROPIC_API_KEY` and others;
- the model overrides: `OPENAI_MODEL2`, `OPENAI_FAST_MODEL2`, `ANTHROPIC_MODEL`, `ANTHROPIC_FAST_MODEL`,
  `GEMINI_MODEL`, `GEMINI_FAST_MODEL`, `LMSTUDIO_MODEL` and others;
- the endpoint overrides: `DEEPSEEK_API_URL`, `MOONSHOT_API_URL`, `LMSTUDIO_URL`;
- `AS_INSECURE_TLS=1`, which stops TLS verification for the platform only.

## How `load_env()` works

1. `load_env()` reads `.env` one time for each process.
2. It copies each value into the process environment. It does not change a variable that the process
   already has.
3. It keeps a list of the names that it copied. `from_process(name)` uses this list. It gives `None` for a
   value that came only from `.env`.
4. It writes the list to `AGENTKIT_DOTENV_KEYS`. A child process reads this list. Thus the child knows which
   inherited values came from `.env`.

### Why the list is necessary

The official runner injects some variables into the process: `AGENTSWITCH_TOKEN`, `AGENTSWITCH_BASE_URL`
and `OPENAI_API_KEY`. These variables change the login mode and the LLM routing. A copy of them in `.env`
must not have the same effect.

The batch starts each task in a child process. Before 2026-10-14, the child got the `.env` copies in its
environment and used them as injected values. A live batch then sent each answer to OpenAI first. The list in
`AGENTKIT_DOTENV_KEYS` stops this. A value that the runner injects is not on the list, so it still counts.

Importing `as_client` also loads `.env`.

## How to test

Run `python -m pytest tests_local/test_env_token_mode.py tests_local/test_config_models.py -q`. These
tests are offline. The hand-written template is `tests/test_config_models.py`.
