# Cost analysis

All numbers below come from tables in `AI_FINOPS` and were produced on synthetic data unless stated.

## Detection (60 days, 6 apps, 8 injected scenarios)

| Detector | Threshold | Precision | Recall | F1 | FPR | Scenarios caught | Delay |
|---|---|---|---|---|---|---|---|
| Z-score (7-day) | HIGH | 0.889 | 0.235 | 0.372 | 0.3% | 8/8 | 0 days |
| Z-score (7-day) | HIGH+WARNING | 0.413 | 0.559 | 0.475 | 9.1% | 8/8 | 0 days |
| Isolation Forest | HIGH | 0.588 | 0.294 | 0.392 | 2.4% | 6/8 | 0 days |
| Isolation Forest | HIGH+WARNING | 0.455 | 0.441 | 0.448 | 6.1% | 6/8 | 0 days |

Source: `DETECTION.DETECTOR_BENCHMARK`, `evaluation/benchmark.json`.

Day-level recall is low by design of the rolling baseline: from the second anomalous day on, the anomaly is
part of the 7-day baseline. Scenario-level detection (first day) is what alerting needs.

Root cause: 8/8 incidents got the expected cause, each with a single driver (confidence 0.95). One extra
HIGH-severity false positive was classified `UNKNOWN` (confidence 0.30).

## Savings simulation (playbook fixes applied as counterfactuals)

| Application | Cause | Credits before | Credits after | Saving |
|---|---|---|---|---|
| sql-agent | RETRY_LOOP | 37.19 | 7.58 | 80% |
| research-agent | AGENT_LOOP | 22.57 | 6.02 | 73% |
| rag-support-agent | RAG_OVER_RETRIEVAL | 16.57 | 4.58 | 72% |
| classification-service | MODEL_ROUTING_CHANGE | 11.10 | 0.52 | 95% |
| research-agent | OUTPUT_INFLATION | 9.29 | 6.97 | 25% |
| document-agent | PROMPT_INFLATION | 8.13 | 2.63 | 68% |
| document-agent | REPEATED_CONTEXT | 7.27 | 2.53 | 65% |
| summarization-service | DUPLICATE_REQUESTS | 1.92 | 1.26 | 34% |
| **All incidents** | | **114.0** | **32.1** | **72%** |

30-day window: 458.1 → 379.2 credits (**-17.2%**), 6 incidents in the window.
Source: `DETECTION.SAVINGS_SIMULATION`, `evaluation/savings_simulation.json`.

Quality: only the model-routing fix changes the model. Routing classification back to mistral-7b changes measured
accuracy from 100% (claude-sonnet-4-5) to 83.6% on the validated ticket set; every other fix is assumed
quality-neutral (assumption, not measured).

## Model routing (67 validated support tickets, 5 classes, 18 ambiguous)

| Model | Accuracy | Credits / 1K requests | Saving vs Claude |
|---|---|---|---|
| mistral-7b | 83.6% | 0.009 | 99.5% |
| llama3.1-8b | 89.6% | 0.012 | 99.3% |
| **llama3.1-70b (recommended at ≥ 95%)** | **95.5%** | **0.038** | **97.7%** |
| claude-sonnet-4-5 | 100%* | 1.667 | – |

\*Claude also validated the labels, so its accuracy is biased upward by construction.

Rates are this account's billed credits per token (ADR 003). Claude's cost is mostly structured-output prompt
overhead (~750 prompt tokens vs ~80 for the other models).

The first, template-based eval set (60 tickets from 20 templates) put mistral-7b at 96.7% and recommended it;
the harder set reversed that, which is why the template set was replaced.

## What this project cost to build

Cortex credits recorded in `CORTEX_AI_FUNCTIONS_USAGE_HISTORY` so far: **~0.38 credits**
(Claude ~0.37 of that: routing eval and label validation). Warehouse time on X-Small `COMPUTE_WH` for SQL and the
Isolation Forest procedure comes on top (1 credit/hour while running). `ACCOUNT_USAGE` lags by up to a few hours,
so the latest calls may not be counted yet.
