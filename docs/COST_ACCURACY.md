# Cost and accuracy of each LLM route (gap G12)

*Written 2026-10-15 in ASD-STE100 (Simplified Technical English) style. Data: seven live batches of all 12
tasks, 2026-10-14 and 2026-10-15. Each batch is a dry run on the live platform.*

## The question

Gap G12 in [`RESEARCH_GAP_ANALYSIS.md`](RESEARCH_GAP_ANALYSIS.md) asks for a comparison of cost and accuracy
(Kapoor et al., *AI Agents That Matter*). The baseline is the agent with template answers only, at $0. Each
LLM route must show what it adds for its cost.

## How to make the table

```bash
python -m agentkit.harness.batch --batch-id <id> --grade             # one arm: the LLM routes of routing.toml
python -m agentkit.harness.batch --batch-id <id> --skip-llm --grade  # the $0 baseline
python -m agentkit.harness.pareto runs/batches/<id> ... [--out table.md]
```

`agentkit.harness.pareto` reads only the saved files. Each batch is one arm. The tool gives these values for
each arm:

- the pass rate, with a 95% Wilson interval;
- the mean partial credit;
- the source of each answer (LLM or template);
- the runs that escalated to a second model;
- the cost, and the cost for each passed run;
- the mean run time;
- whether the arm is on the Pareto frontier.

## The results

| Arm (main model) | Batch | Runs | Passed | Pass rate (95% CI) | Answers LLM / template | Escalated | Cost (USD) | USD for each pass | Mean seconds | Mean output tokens | Frontier |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Template only (no LLM) | `live-template-2026-10-15` | 12 | 12 | 1.00 (0.76 to 1.00) | 0 / 12 | 0 | 0.0000 | 0.0000 | 8.9 | 0 | yes |
| OpenAI gpt-6-luna | `live-llm-openai-first-2026-10-14` | 12 | 12 | 1.00 (0.76 to 1.00) | 12 / 0 | 0 | 0.0036 | 0.0003 | 12.5 | 201 | |
| Gemini 3.5 Flash-Lite | `live-llm-gemini-2026-10-14` | 12 | 12 | 1.00 (0.76 to 1.00) | 12 / 0 | 0 | 0.0042 | 0.0003 | 10.7 | 276 | |
| OpenAI gpt-4o-mini (runner default) | `live-llm-deepseek-2026-10-14` | 12 | 12 | 1.00 (0.76 to 1.00) | 12 / 0 | 0 | 0.0049 (see note 1) | 0.0004 | 11.6 | 179 | |
| DeepSeek deepseek-flash | `live-llm-deepseek-2026-10-14b` | 12 | 12 | 1.00 (0.76 to 1.00) | 12 / 0 | 0 | 0.0249 | 0.0021 | 16.1 | 1,209 | |
| Claude Haiku 5.5 | `live-llm-claude-gemini-2026-10-14` | 12 | 12 | 1.00 (0.76 to 1.00) | 12 / 0 | 1 (to Sonnet 5.5) | 0.0296 | 0.0025 | 16.6 | 1,453 | |
| DeepSeek deepseek-flash (second batch) | `live-llm-models-2026-10-14` | 12 | 12 (see note 2) | 1.00 (0.76 to 1.00) | 11 / 1 | 1 (to deepseek-v4-pro) | 0.0364 | 0.0030 | 19.7 | — | |

Notes:

1. The ledger of that batch shows $0.0264. At that time, `economics.py` had no price for `gpt-4o-mini`, so the
   ledger used the default price ($1 for each million tokens, input and output). The table shows the cost at
   the list price ($0.15 and $0.60). `economics.py` now has that price.
2. That batch passed 11 of 12 when the grader first graded it. Task t10 failed on a true disclaimer. After
   the correction of the grader, the saved files give 12 of 12.

## Findings

1. **The grader cannot see what the LLM adds.** All seven arms pass 12 of 12. The template-only arm also
   passes 12 of 12, at $0. Thus the template arm is the full Pareto frontier.
2. **The reason.** Code calculates each fact in the finding. The claim audit stops each LLM answer that
   changes a fact. Thus all arms state the same facts, and the checks grade only facts. The LLM adds
   readability (plain prose, the most important point first). No check measures that.
3. **The difference between the LLM arms is cost, not accuracy.** The cost for each pass changes by a factor
   of 10, from $0.0003 (gpt-6-luna, Gemini Flash-Lite) to $0.0030 (deepseek-flash).
4. **Hidden reasoning is most of the cost.** deepseek-flash and Claude Haiku 5.5 write about 1,200 to 1,450
   output tokens for each answer. Most of these tokens are hidden reasoning. gpt-6-luna (with `reasoning_effort = "none"`) writes about 200 tokens for
   an answer of the same length. Each provider bills the reasoning tokens as output tokens.
5. **A reasoning model can stop before its answer.** In `live-llm-models-2026-10-14`, task t12 escalated to
   deepseek-v4-pro. That model used 5,342 output tokens and reached the limit of 4,096 tokens for the answer
   (`max_tokens`). Thus its answer was cut off, and the template gave the answer. The task still passed. The
   cascade worked as designed, but the money for that call gave no answer.
6. **The sample is small.** Each arm has 12 runs. A pass rate of 12 of 12 only shows that the true rate is
   probably 0.76 or more. The arms ran at different times on the live platform.

## Recommendations

1. **Keep the cheapest audited route first in the `fast` tier.** gpt-6-luna and Gemini 3.5 Flash-Lite give the
   same graded result as the other models, at about one tenth of the cost. The current order already puts
   gpt-6-luna first.
2. **Turn off hidden reasoning for narration where the provider permits it.** The narration only writes facts
   that code calculated. Reasoning tokens add cost and add no graded value.
3. **Give reasoning models in the `quality` tier more output tokens, or a lower reasoning effort.** This
   prevents the cut-off answer of finding 5.
4. **Measure readability, or accept that the LLM is optional.** To show the value of the LLM, add a check for
   the quality of the text. Examples: the verdict in the first sentence, no repeated facts, a length limit.
   Calibrate such a check on mutants, as the other checks. Without such a check, the template-only agent is
   the best arm.
5. **Repeat each arm (`--repeat 3`)** before you decide between arms whose cost is near. This gives more runs
   and a narrower interval.

## Related documents

- [`RESEARCH_GAP_ANALYSIS.md`](RESEARCH_GAP_ANALYSIS.md), gap G12
- [`explainers/agentkit_llm.md`](explainers/agentkit_llm.md): the providers, the tiers and the cascade
- [`../tests/MANUAL_TEST_LOG.md`](../tests/MANUAL_TEST_LOG.md): rows A-LIVE-05 to A-LIVE-10
