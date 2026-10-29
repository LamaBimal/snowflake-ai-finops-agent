# Snowflake AI FinOps Agent

AI-powered FinOps platform for detecting abnormal LLM token usage, identifying the root cause of AI cost spikes, and generating optimization recommendations using Snowflake, Cortex AI, statistical anomaly detection, and model-routing strategies.

## Overview

Generative AI applications can become expensive quickly when prompt sizes grow, retrieval pipelines inject excessive context, large models are used for simple tasks, or agents enter retry loops.

This project builds an **AI FinOps intelligence layer on Snowflake** that continuously analyzes AI usage and answers three important questions:

1. **Did AI usage or cost behave abnormally?**
2. **What caused the anomaly?**
3. **What action can reduce cost without significantly reducing quality?**

The platform combines deterministic analytics, statistical anomaly detection, root-cause analysis, Cortex-powered explanations, and optimization recommendations.

---

## Key Features

- LLM token and credit usage monitoring
- AI cost anomaly detection
- Prompt inflation detection
- Excessive output-token detection
- Request-volume spike detection
- Retry-loop detection
- RAG over-retrieval identification
- Expensive model-routing detection
- Application-level AI cost attribution
- Root-cause analysis
- AI-generated explanations
- Cost optimization recommendations
- Model cost-vs-quality evaluation
- Streamlit monitoring dashboard
- Synthetic AI usage generation for testing
- Benchmarking of anomaly-detection techniques

---

## Example

### Detected Anomaly

```text
Application: rag-support-agent
Severity: HIGH

Expected Credits: 5.1
Observed Credits: 17.2

Increase: +237%

Input Tokens / Request
1,900 → 6,400

Request Volume
+4%

Model
Unchanged
```

### Root Cause

```text
Primary Cause:
RAG context inflation

Evidence:
- Input tokens increased by 237%
- Request volume remained almost unchanged
- Model selection did not change
- Retrieval top_k increased from 5 to 20
```

### Recommendation

```text
Reduce RAG top_k from 20 to 5–8.

Estimated Cost Saving:
30–45%

Expected Quality Risk:
Low to Medium
```

---

# Architecture

```text
                     AI Workloads
                          │
             ┌────────────┼────────────┐
             │            │            │
        Cortex AI     Cortex Agents   Search / RAG
             │            │            │
             └────────────┼────────────┘
                          │
                          ▼
               Snowflake Usage History
                          │
                          ▼
                  Usage Analytics Layer
                          │
              ┌───────────┼───────────┐
              │           │           │
          Token KPIs   Cost KPIs   Request KPIs
              │           │           │
              └───────────┼───────────┘
                          ▼
                Anomaly Detection Engine
                   /                \
                  /                  \
          Statistical Rules     ML Detection
           Z-Score / IQR      Isolation Forest
                  \                  /
                   \                /
                          ▼
                  Root Cause Engine
                          │
                          ▼
                     Cortex AI
                          │
                          ▼
              Optimization Recommendations
                          │
                          ▼
                  Streamlit Dashboard
```

---

# Technology Stack

## Data Platform

- Snowflake
- Snowflake SQL
- Streams
- Tasks
- ACCOUNT_USAGE views

## AI

- Snowflake Cortex AI
- Cortex Agents
- Cortex Search
- LLM-based explanation generation

## Machine Learning

- Z-score anomaly detection
- Rolling statistical baselines
- Interquartile Range
- Isolation Forest

## Application

- Streamlit in Snowflake
- Python

## Testing and Evaluation

- Synthetic usage datasets
- Known injected anomaly scenarios
- Precision
- Recall
- F1 Score
- False-positive rate
- Detection delay
- Cost reduction
- Response-quality comparison

---

# Project Structure

```text
snowflake-ai-finops-agent/
│
├── README.md
│
├── architecture/
│   ├── architecture.md
│   └── decisions/
│
├── sql/
│   ├── 01_setup.sql
│   ├── 02_usage_view.sql
│   ├── 03_usage_metrics.sql
│   ├── 04_daily_metrics.sql
│   ├── 05_anomaly_detection.sql
│   └── 06_tasks.sql
│
├── data/
│   ├── synthetic_usage.py
│   └── anomaly_scenarios/
│
├── anomaly_detection/
│   ├── statistical.py
│   ├── isolation_forest.py
│   └── scoring.py
│
├── root_cause/
│   └── rules.py
│
├── agent/
│   ├── root_cause_agent.py
│   ├── optimization_agent.py
│   └── prompts/
│
├── model_routing/
│   ├── evaluator.py
│   └── optimizer.py
│
├── evaluation/
│   ├── benchmark.json
│   ├── anomaly_evaluation.py
│   └── quality_evaluation.py
│
├── streamlit/
│   └── app.py
│
├── tests/
│
└── docs/
    ├── governance.md
    ├── cost-analysis.md
    └── lessons-learned.md
```

---

# Snowflake Data Model

The project normalizes AI telemetry into an application-friendly analytics model.

## AI_USAGE_METRICS

```text
usage_time
query_id
application
user_id
role_name
function_name
model_name

input_tokens
output_tokens
total_tokens

credits
request_count

tokens_per_request
credits_per_request
```

Applications can be identified through Snowflake query tags.

Example:

```sql
ALTER SESSION SET QUERY_TAG = 'rag-support-agent';
```

Possible applications:

```text
rag-support-agent
sql-agent
document-agent
summarization-service
classification-service
research-agent
```

---

# Snowflake Usage Source

The initial implementation uses Cortex AI usage telemetry exposed through Snowflake's Account Usage schema.

Example:

```sql
SELECT
    DATE_TRUNC('DAY', START_TIME) AS USAGE_DATE,
    FUNCTION_NAME,
    MODEL_NAME,
    SUM(CREDITS) AS TOTAL_CREDITS,
    COUNT(DISTINCT QUERY_ID) AS QUERY_COUNT
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
WHERE START_TIME >= DATEADD('DAY', -30, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3
ORDER BY USAGE_DATE DESC;
```

The normalized analytics layer is built on top of this usage information.

---

# Metrics

The platform tracks AI consumption across multiple dimensions.

## Cost Metrics

```text
total_credits
credits_per_request
credits_per_application
credits_per_model
credits_per_user
credits_per_function
```

## Token Metrics

```text
input_tokens
output_tokens
total_tokens
tokens_per_request
input_output_ratio
```

## Operational Metrics

```text
request_count
retry_count
failure_rate
latency
model_distribution
application_distribution
```

---

# Supported Anomaly Types

## 1. Token Spike

Abnormally high token consumption.

```text
Normal:
2.4M tokens/day

Observed:
8.9M tokens/day
```

---

## 2. Prompt Inflation

Input tokens per request increase significantly.

Possible causes:

- full conversation history added repeatedly
- large system prompts
- excessive metadata
- unnecessary context

---

## 3. Output Inflation

Model responses become unnecessarily long.

Possible optimization:

```text
MAX_OUTPUT_TOKENS
2000 → 800
```

---

## 4. RAG Over-Retrieval

Too many retrieved chunks are added to the prompt.

Example:

```text
Normal
top_k = 5

Anomalous
top_k = 25
```

---

## 5. Request Spike

Unexpected increase in request volume.

Possible causes:

- traffic increase
- retry loops
- application bugs
- duplicated requests

---

## 6. Retry Loop

Repeated execution of similar AI requests caused by application failures.

---

## 7. Model Routing Anomaly

A high-cost model is used for tasks that could be handled by a smaller model.

Example:

```text
Classification
      ↓
Large Reasoning Model
```

Recommended:

```text
Classification
      ↓
Small Model
```

---

# Statistical Anomaly Detection

The first implementation uses rolling statistics.

For every application:

```text
Current Metric
      ↓
7-Day Historical Baseline
      ↓
Average + Standard Deviation
      ↓
Z-Score
```

Example severity levels:

```text
|Z| < 2

NORMAL

2 <= |Z| < 3

WARNING

|Z| >= 3

HIGH
```

Example SQL:

```sql
WITH DAILY_USAGE AS (

    SELECT
        DATE_TRUNC('DAY', USAGE_TIME) AS USAGE_DATE,
        APPLICATION,
        SUM(TOTAL_TOKENS) AS TOKENS,
        SUM(CREDITS) AS CREDITS
    FROM AI_FINOPS.ANALYTICS.AI_USAGE_METRICS
    GROUP BY 1, 2

),

BASELINE AS (

    SELECT
        *,
        AVG(CREDITS) OVER (
            PARTITION BY APPLICATION
            ORDER BY USAGE_DATE
            ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
        ) AS AVG_CREDITS,

        STDDEV(CREDITS) OVER (
            PARTITION BY APPLICATION
            ORDER BY USAGE_DATE
            ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
        ) AS STD_CREDITS

    FROM DAILY_USAGE
)

SELECT
    *,
    (CREDITS - AVG_CREDITS)
        / NULLIF(STD_CREDITS, 0) AS Z_SCORE
FROM BASELINE;
```

---

# Machine Learning Detection

After the statistical baseline is implemented, the project adds:

```text
Isolation Forest
```

The project then compares:

```text
Z-Score
vs
Isolation Forest
```

Evaluation metrics:

```text
Precision
Recall
F1 Score
False Positive Rate
Detection Delay
```

---

# Root Cause Analysis

Anomalies are first interpreted using deterministic rules.

Example:

```python
if request_growth > 2:
    cause = "REQUEST_VOLUME_SPIKE"

elif input_tokens_per_request_growth > 2:
    cause = "PROMPT_INFLATION"

elif output_tokens_per_request_growth > 2:
    cause = "OUTPUT_INFLATION"

elif model_changed:
    cause = "MODEL_ROUTING_CHANGE"

elif retry_ratio > threshold:
    cause = "RETRY_LOOP"
```

This prevents the LLM from performing unsupported root-cause guessing.

The architecture follows:

```text
Metrics
   ↓
Anomaly Detection
   ↓
Evidence
   ↓
Root Cause Rules
   ↓
Cortex AI
   ↓
Human-Friendly Explanation
```

---

# AI Optimization Agent

The optimization layer generates recommendations based on the detected root cause.

| Problem            | Recommendation                 |
| ------------------ | ------------------------------ |
| Prompt inflation   | Reduce context/history         |
| RAG over-retrieval | Reduce retrieval top_k         |
| Output inflation   | Reduce max output tokens       |
| Model over-sizing  | Route task to smaller model    |
| Retry loop         | Add retry and backoff policies |
| Duplicate requests | Introduce caching              |
| Agent loop         | Limit agent iterations         |
| Repeated context   | Reuse or cache static context  |

---

# Model Routing Optimization

One advanced goal of the project is to optimize:

```text
AI Cost
vs
Response Quality
```

Example experiment:

```text
Large Model

Accuracy: 94%
Cost:     $100
```

Compared with:

```text
Small Model

Accuracy: 92%
Cost:     $28
```

Recommendation:

```text
Use the smaller model for classification.

Estimated Saving:
72%

Quality Difference:
-2%
```

The optimization problem can be expressed as:

```text
Minimize:

AI Cost

Subject to:

Accuracy >= Minimum Quality Threshold

Latency <= Maximum Latency

Safety >= Required Threshold
```

---

# Synthetic Data

The repository includes a synthetic AI-usage generator so anomaly scenarios can be tested even when sufficient historical Cortex usage is unavailable.

Baseline example:

```text
Application:
rag-support-agent

Requests / Day:
800–1000

Input Tokens / Request:
1500–2200

Output Tokens / Request:
300–600

Credits / Day:
4–6
```

---

# Injected Anomaly Scenarios

The project intentionally injects known anomalies to evaluate detector performance.

## Scenario 1 — Prompt Inflation

```text
Input Tokens / Request

1800
 ↓
6500
```

---

## Scenario 2 — RAG Over-Retrieval

```text
top_k

5
 ↓
25
```

---

## Scenario 3 — Expensive Model Routing

```text
Small Model
 ↓
Large Reasoning Model
```

---

## Scenario 4 — Retry Loop

```text
900 requests/day
 ↓
4800 requests/day
```

---

## Scenario 5 — Excessive Output

```text
Average Output

450 tokens
 ↓
1900 tokens
```

---

# Streamlit Dashboard

The first version of the UI contains four main areas.

## AI Spend Overview

```text
Credits            17.2
Tokens              8.7M
Requests             3,450

Cost Change         +218%
```

## Anomaly Center

```text
Severity: HIGH

Application:
rag-support-agent

Expected:
5.1 credits

Actual:
17.2 credits
```

## Root Cause

```text
Input Token Inflation

Normal:
1,900 tokens/request

Observed:
6,400 tokens/request
```

## Optimization Recommendation

```text
Reduce RAG retrieval:

top_k
20 → 6

Estimated Saving:
~36%

Quality Risk:
LOW
```

---

# Evaluation Framework

The anomaly detection system is evaluated against known injected anomalies.

Metrics include:

```text
Anomaly Precision
Anomaly Recall
F1 Score
False Positive Rate
Detection Delay
```

The AI optimization component is evaluated using:

```text
Cost Before Optimization
Cost After Optimization

Token Reduction

Response Quality Before
Response Quality After

Estimated Savings
Realized Savings
```

Example target result:

```text
30-Day Simulation

AI Cost Before:          $1,850
AI Cost After:           $1,124

Cost Reduction:          39.2%

Response Quality Before: 91.3%
Response Quality After:  90.7%

Quality Difference:      -0.6%

Anomaly Precision:       92.8%
```

---

# Implementation Roadmap

## Phase 1 — Foundation

- Create Snowflake database and schemas
- Explore Cortex AI usage data
- Create normalized usage model
- Add query-tag-based application attribution

## Phase 2 — Synthetic Workload

- Generate 30–60 days of AI usage
- Inject known anomaly scenarios
- Create baseline metrics

## Phase 3 — Detection

- Implement rolling baseline
- Implement Z-score detection
- Create severity scoring
- Persist detected anomalies

## Phase 4 — Root Cause Analysis

- Build deterministic root-cause rules
- Capture supporting evidence
- Generate confidence scores

## Phase 5 — Cortex AI

- Generate anomaly explanations
- Generate optimization recommendations
- Add evidence to AI prompts

## Phase 6 — Dashboard

- AI spend overview
- anomaly center
- root-cause analysis
- recommendation view

## Phase 7 — ML

- Add Isolation Forest
- benchmark against statistical detection

## Phase 8 — Optimization

- model-routing experiments
- token optimization
- cost-vs-quality analysis

---

# Research Questions

This project can also be used as an experimental AI engineering study.

Possible research questions:

> Can automated anomaly detection identify abnormal LLM spending accurately enough for enterprise AI FinOps?

> Can AI-generated optimization recommendations reduce LLM inference cost while preserving response quality?

> How do statistical anomaly detection and Isolation Forest compare when detecting LLM usage anomalies?

> Can task-aware model routing reduce AI inference cost without materially affecting application quality?

---

# Design Principles

The project follows several architectural principles.

### Deterministic Detection Before LLM Reasoning

LLMs should explain evidence rather than invent anomalies.

```text
Data
 ↓
Statistics / ML
 ↓
Evidence
 ↓
AI Explanation
```

### Cost Optimization Must Consider Quality

The cheapest model is not always the best model.

The goal is:

```text
Lowest acceptable cost

while maintaining

Required quality
```

### Recommendations Must Be Explainable

Each recommendation should include:

```text
Problem
Evidence
Recommendation
Estimated Saving
Quality Risk
Confidence
```

---

# Future Enhancements

Potential future improvements include:

- real-time anomaly alerts
- AI cost forecasting
- application budgets
- cost attribution by department/team
- intelligent model routing
- prompt optimization recommendations
- RAG retrieval optimization
- Cortex Agent usage monitoring
- multi-agent cost analysis
- configurable anomaly thresholds
- Slack/email alerts
- historical savings tracking
- automated recommendation validation
- AI workload benchmarking

---

# Project Goal

The goal of this project is not simply to build another AI monitoring dashboard.

It is to demonstrate how **AI workloads themselves can be analyzed, governed, and optimized using data engineering, statistical ML, FinOps principles, and generative AI**.

The project aims to answer:

```text
What happened?

Why did it happen?

How much did it cost?

What should we change?

How much can we save?

Will the change hurt AI quality?
```

---

## Status

🚧 **Under Active Development**

Current focus:

```text
Snowflake usage ingestion
        ↓
Normalized AI metrics
        ↓
Synthetic anomaly generation
        ↓
Statistical anomaly detection
```

---

## License

This project is intended for educational, research purposes.
