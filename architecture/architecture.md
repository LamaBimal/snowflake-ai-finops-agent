# Architecture

## Data flow

```text
SNOWFLAKE.ACCOUNT_USAGE                              RAW.SYNTHETIC_USAGE (+ stream)
  CORTEX_AI_FUNCTIONS_USAGE_HISTORY ─┐                  data/synthetic_usage.py
  CORTEX_AGENT_USAGE_HISTORY ────────┤                  8 injected scenarios -> RAW.ANOMALY_LABELS
  CORTEX_SEARCH_DAILY_USAGE_HISTORY ─┤                             │
                                     ▼                             ▼
             ANALYTICS.V_CORTEX_USAGE / V_CORTEX_AGENT_USAGE / V_CORTEX_SEARCH_USAGE
                                     │
                                     ▼
                     ANALYTICS.AI_USAGE_METRICS (SOURCE = REAL | SYNTHETIC)
                                     │
                                     ▼
                     ANALYTICS.DAILY_METRICS  (one row per app per UTC day)
                                     │
             ┌───────────────────────┴───────────────────────┐
             ▼                                               ▼
 DETECTION.V_ZSCORE (7-day rolling, 9 metrics)   DETECTION.V_IF_FEATURES (log ratio to 7-day mean)
             │  SP_DETECT_ANOMALIES                          │  SP_DETECT_ISOLATION_FOREST (scikit-learn)
             └───────────────────────┬───────────────────────┘
                                     ▼
                            DETECTION.ANOMALIES (DETECTOR column)
                                     │  SP_BUILD_INCIDENTS (Z-score rows only)
                                     ▼
                DETECTION.INCIDENTS  ── deterministic ROOT_CAUSE + EVIDENCE + CONFIDENCE
                                     │  SP_EXPLAIN_INCIDENTS (AI_COMPLETE, structured output)
                                     ▼
          DETECTION.INCIDENT_EXPLANATIONS + RECOMMENDATION_PLAYBOOK -> V_INCIDENT_REPORT
                                     │
          ┌──────────────────────────┼──────────────────────────────┐
          ▼                          ▼                              ▼
 SAVINGS_SIMULATION        DETECTOR_BENCHMARK             MODEL_ROUTING_RESULTS
 (evaluation/)             (evaluation/)                  (model_routing/)
          └──────────────────────────┴──────────────────────────────┘
                                     ▼
                        streamlit/streamlit_app.py (6 tabs)
```

## Schedule (task graph, created suspended)

```text
TASK_DAILY_DETECTION   06:00 UTC  CALL SP_DETECT_ANOMALIES(3)
 ├─ TASK_BUILD_INCIDENTS          CALL SP_BUILD_INCIDENTS()
 │   └─ TASK_EXPLAIN_INCIDENTS    CALL SP_EXPLAIN_INCIDENTS(FALSE)   -- only new incidents
 └─ TASK_ISOLATION_FOREST         WHEN SYSTEM$STREAM_HAS_DATA(RAW.SYNTHETIC_USAGE_STREAM)
```

Start: `SELECT SYSTEM$TASK_DEPENDENTS_ENABLE('AI_FINOPS.DETECTION.TASK_DAILY_DETECTION');`

## Objects by schema

| Schema | Objects |
|---|---|
| RAW | SYNTHETIC_USAGE, SYNTHETIC_USAGE_STREAM, ANOMALY_LABELS, ROUTING_EVAL_SET, ROUTING_EVAL_CANDIDATES |
| ANALYTICS | V_CORTEX_USAGE, V_CORTEX_AGENT_USAGE, V_CORTEX_SEARCH_USAGE, AI_USAGE_METRICS, DAILY_METRICS |
| DETECTION | V_ZSCORE, V_IF_FEATURES, ANOMALIES, V_INCIDENT_CANDIDATES, INCIDENTS, RECOMMENDATION_PLAYBOOK, INCIDENT_EXPLANATIONS, V_INCIDENT_REPORT, DETECTOR_BENCHMARK, ROUTING_PREDICTIONS, MODEL_ROUTING_RESULTS, SAVINGS_SIMULATION, STREAM_CONSUMPTION_LOG, procedures `SP_*`, tasks `TASK_*` |

## Root-cause rules (first match wins)

| Order | Cause | Condition |
|---|---|---|
| 1 | RETRY_LOOP | retry ratio ≥ 20% and requests ≥ 1.5× |
| 2 | DUPLICATE_REQUESTS | duplicate ratio ≥ 20% and ≥ 2× baseline |
| 3 | AGENT_LOOP | agent steps/request ≥ 2× |
| 4 | REQUEST_VOLUME_SPIKE | requests ≥ 2× |
| 5 | MODEL_ROUTING_CHANGE | primary model changed |
| 6 | REPEATED_CONTEXT | static-prefix tokens/step ≥ 1.5× and input/request ≥ 1.5× |
| 7 | RAG_OVER_RETRIEVAL | dynamic input/step ≥ 1.5× and top_k increased |
| 8 | PROMPT_INFLATION | dynamic input/step ≥ 1.5× |
| 9 | OUTPUT_INFLATION | output/step ≥ 1.5× |
| – | UNKNOWN | none of the above (confidence 0.30) |

Growths are computed after factoring out the explained parts (duplicates, agent steps, static prefix), so one
change does not show up as several drivers. Confidence is 0.95 for a single driver with |z| ≥ 5, 0.80 for a single
driver otherwise, and 0.60 when more than one driver fires. Same rules in SQL (`sql/07_root_cause.sql`) and Python
(`root_cause/rules.py`, unit-tested).

## SQL file order

`01_setup` → `02_usage_view` → `11_agent_search_usage` → `03_usage_metrics` → `04_daily_metrics` →
`05_anomaly_detection` → `06_tasks` → `07_root_cause` → `08_cortex` → `09_isolation_forest` → `10_pipeline`

Run any of them with `python3 common/snowflake_session.py sql/<file>.sql`.
