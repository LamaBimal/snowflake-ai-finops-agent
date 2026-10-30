# ADR 003: Price models with the account's own billed credits

**Status:** Accepted

## Context
Published per-token prices change and differ by region and contract. The model-routing optimizer needs a cost
per request that matches what this account actually pays.

## Decision
`model_routing/optimizer.py` computes a blended credits-per-token rate per model from
`ANALYTICS.V_CORTEX_USAGE` (this account's `CORTEX_AI_FUNCTIONS_USAGE_HISTORY`) and multiplies it by the measured
average tokens per request from the routing eval. No external price list is used.

The synthetic generator uses illustrative rates (`MODEL_RATES` in `data/synthetic_usage.py`); these only shape
the synthetic data and are not used for routing decisions.

## Consequences
- Costs reflect real billing, including structured-output overhead (Claude: ~750 prompt tokens per
  classification vs ~80 for Llama/Mistral).
- `ACCOUNT_USAGE` lags by up to a few hours, so rates computed right after an eval run rest on few calls
  (`RATE_SOURCE_CALLS` column); rerun the optimizer later to refine them.
- Blended rates ignore the input/output price split; acceptable here because output is ~5–15% of tokens.
