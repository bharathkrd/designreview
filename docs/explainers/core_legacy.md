# `core/` — legacy import paths

*Do not import from `core/` in new code. The folder stays only for old scripts and notes. Written in
ASD-STE100 (Simplified Technical English) style, 2026-10-14.*

| Module | Status |
|---|---|
| `core/harness.py` | Gives `TaskRun`, `Step` and `Harness` from `agentkit/record/run_record.py`. The API is the same. |
| `core/llm_gateway.py` | Gives `LLMGateway`, `LLMReply`, `ProviderFault` and others from `agentkit/llm/gateway.py`. `python core/llm_gateway.py` still makes a test call through the gateway. |
| `core/economics.py` | Gives `CostLedger` and the related names from `agentkit/llm/economics.py`. |
| `core/routing.yaml` | A stub. The routing is in `config/routing.toml`. |
| `core/dag_engine.py` | The graph engine of the first draft. **The agent does not use it.** See `agentkit/graph`. It stays until its last tests go. It needs `networkx`. |
| `core/eval_framework.py` | The axis scorer of the first draft (`evaluate_run`). The harness does not use it. |
| `core/judge.py` | A single-pass LLM-as-judge rubric. It is not part of the grading. You can use it as an optional, extra signal. |

When you remove these modules, also remove `networkx` from `requirements.txt`.
