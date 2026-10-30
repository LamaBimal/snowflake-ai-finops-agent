# Lessons learned

## Data and telemetry
- **`CORTEX_AI_FUNCTIONS_USAGE_HISTORY` is hourly.** `START_TIME`/`END_TIME` are hour buckets, so it cannot give
  per-call latency. Latency is left NULL rather than reporting a misleading 1-hour figure.
- **Query tags come in two shapes.** Some tools write plain strings, others JSON (`{"app": ...}`). Parse both.
- **`ACCOUNT_USAGE` lags.** Credit rates computed right after an experiment rest on a handful of calls.
- **Bucket days in UTC.** Grouping UTC timestamps in the session's local time zone produced 61 days from 60.

## Detection
- **A rolling baseline absorbs the anomaly.** From day 2 the incident is in the 7-day baseline, so day-level
  recall stays low even with perfect first-day detection. Measure scenario-level detection and delay as well.
- **Ratios near zero need an absolute std floor.** A 1% duplicate ratio moving to 1.17% scored z = 2.3 until a
  0.005 floor was added.
- **Leading WARNING days distort incidents.** Merging a noisy WARNING day into the following HIGH day shifted the
  incident start and its baseline. Incidents now start at the first HIGH day.
- **Isolation Forest needs the same features as the rules.** It caught 4/8 scenarios until the three new metrics
  (duplicate ratio, agent steps, static-context ratio) were added as features, then 6/8.

## Root cause
- **Factor out explained growth.** An agent loop raises steps, input and output together; dividing token growth by
  step growth keeps it a single driver. Same for duplicates (unique requests) and static prefixes (dynamic input).
- **Generate counterfactual-friendly synthetic data.** The static prefix had to be sized from the baseline input;
  otherwise prompt inflation also looked like repeated context.

## LLMs and evaluation
- **Template eval sets flatter small models.** On 20 templates mistral-7b scored 96.7%; on varied, partly
  ambiguous tickets it scored 83.6% and the recommended model changed.
- **Validator bias.** Using Claude to validate labels makes Claude look perfect on the same set. Use a different
  validator or human labels for a fair large-model baseline.
- **Structured output needs headroom.** With `max_tokens = 20`, Claude's JSON was cut off and every call failed
  validation; 100 works for all models. Structured output also added ~700 prompt tokens per Claude call.
- **Keep the LLM out of the numbers.** Explanations restated evidence well, but one called a 1% baseline "0%".
  Saving estimates and evidence shown in the UI come from SQL.

## Platform
- **Owner's-rights procedures cannot create temporary tables**; stage through a transient table.
- **Snowflake Scripting blocks inside tasks** need `EXECUTE IMMEDIATE $$ … $$` when the deploy script splits
  statements on `;`.
- **`/workspace` is a stage mount.** Files written without closing the handle may not be flushed; one edit left a
  truncated file. Close files explicitly and re-check file tails after writes.
