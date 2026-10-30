# Snowflake AI FinOps Agent

Detects abnormal Cortex AI token and credit usage, explains the root cause from evidence, and recommends fixes
with a cost-vs-quality check. Everything runs in Snowflake (`AI_FINOPS` database).

```text
Usage telemetry -> daily metrics -> anomaly detection -> deterministic root cause -> Cortex explanation
                                                                                   -> savings + quality check
```

## Interactive walkthrough

Explore the [How It Works page](https://lamabimal.github.io/snowflake-ai-finops-agent/) for a visual explanation of the agent. Click the boxes in the pipeline diagram to inspect each stage, from usage telemetry and daily metrics through anomaly detection, root-cause analysis, Cortex AI explanations, and recommendations.

The page explains the three questions the agent answers:

- **Did AI cost behave abnormally?** A rolling 7-day Z-score across 9 daily metrics per application, with Isolation Forest as a second detector.
- **What caused it?** Ordered, deterministic rules evaluate before-and-after evidence; Cortex AI explains the findings.
- **What should change, and is it safe?** Recommendations combine a playbook action, simulated savings, and measured quality impact for model changes.

Page source: [docs/index.html](docs/index.html).

### GitHub Pages publishing

To publish `docs/index.html` at the site home page, configure **Settings → Pages → Deploy from a branch → main → /docs**, or use **GitHub Actions** as the Pages source and set the upload path in [the deployment workflow](.github/workflows/static.yml) to `'./docs'`.

## Status

| Phase | State |
|---|---|
| 1. Foundation: database, normalized usage views (AI functions, Cortex Agents, Cortex Search) | Done |
| 2. Synthetic workload: 60 days, 6 apps, 8 injected scenarios | Done |
| 3. Detection: 7-day rolling Z-score on 9 metrics | Done |
| 4. Root cause: ordered rules with evidence and confidence (SQL + Python) | Done |
| 5. Cortex explanations + recommendation playbook | Done |
| 6. Streamlit dashboard (6 tabs) | Done; launch with **Run** |
| 7. Isolation Forest (in Snowflake) + benchmark | Done |
| 8. Model-routing cost vs quality on a validated ticket set | Done |
| Scheduling: stream + task graph | Created **suspended** |

Not covered: Slack/email alerts, Streamlit authentication, latency for AI functions (the usage view is hourly).

## Results (synthetic data)

- Detection: Z-score catches **8/8** scenarios on day one; HIGH-only precision 0.89, FPR 0.3%.
- Root cause: **8/8** correct, single driver each; one false positive left as `UNKNOWN`.
- Savings simulation: incident spend 114.0 → 32.1 credits (**-72%**); 30-day spend **-17.2%**.
- Model routing at ≥ 95% accuracy: **llama3.1-70b** (95.5%), 97.7% cheaper than claude-sonnet-4-5.

Details: [docs/cost-analysis.md](docs/cost-analysis.md).

## Anomaly types

Retry loop, duplicate requests, agent loop, request volume spike, model routing change, repeated static
context, RAG over-retrieval, prompt inflation, output inflation. Rules: [architecture/architecture.md](architecture/architecture.md).

## Project structure

```text
snowflake-ai-finops-agent/
├── README.md
├── architecture/
│   ├── architecture.md
│   └── decisions/                 001 deterministic root cause, 002 IF in Snowflake, 003 billed rates
├── sql/                           01_setup … 11_agent_search_usage (run order in architecture.md)
├── common/snowflake_session.py    session helper + SQL file runner
├── data/
│   ├── synthetic_usage.py
│   └── anomaly_scenarios/scenarios.json
├── anomaly_detection/             statistical.py (scoring), isolation_forest.py
├── root_cause/rules.py
├── agent/                         root_cause_agent.py, optimization_agent.py, prompts/
├── model_routing/                 build_eval_set.py, evaluator.py, optimizer.py
├── evaluation/                    anomaly_evaluation.py, quality_evaluation.py, savings_simulation.py, *.json
├── streamlit/                     streamlit_app.py, snowflake.yml, pyproject.toml
├── tests/                         test_rules.py, test_evaluation.py
└── docs/                          index.html (interactive walkthrough), governance.md, cost-analysis.md, lessons-learned.md
```

## Run

```bash
# 1. Objects (order matters)
python3 common/snowflake_session.py sql/01_setup.sql sql/02_usage_view.sql sql/11_agent_search_usage.sql \
  sql/03_usage_metrics.sql sql/04_daily_metrics.sql sql/05_anomaly_detection.sql sql/06_tasks.sql \
  sql/07_root_cause.sql sql/08_cortex.sql sql/09_isolation_forest.sql sql/10_pipeline.sql

# 2. Synthetic data, detection, incidents, explanations
python3 data/synthetic_usage.py
python3 agent/root_cause_agent.py
python3 anomaly_detection/isolation_forest.py
python3 agent/optimization_agent.py            # Cortex calls (~1 per new incident)

# 3. Evaluation
python3 evaluation/anomaly_evaluation.py
python3 model_routing/build_eval_set.py        # Cortex calls (~120)
python3 model_routing/evaluator.py             # Cortex calls (4 models x eval set)
python3 model_routing/optimizer.py 0.95
python3 evaluation/savings_simulation.py

# 4. Tests
python3 tests/test_rules.py && python3 tests/test_evaluation.py
```

Schedule the daily pipeline (children first, root last):

```sql
SELECT SYSTEM$TASK_DEPENDENTS_ENABLE('AI_FINOPS.DETECTION.TASK_DAILY_DETECTION');
```

Tag AI workloads so spend is attributed: `ALTER SESSION SET QUERY_TAG = 'rag-support-agent';`
(JSON tags with an `app` key also work).

## Design principles

- Deterministic detection and root cause before LLM reasoning; the LLM only explains the evidence.
- Recommendations carry problem, evidence, action, estimated saving, quality risk and confidence.
- Cost decisions are checked against measured quality, not assumed.

See [docs/governance.md](docs/governance.md) and [docs/lessons-learned.md](docs/lessons-learned.md).

## License

Educational, research and portfolio use. Choose an open-source license before public distribution.

