# ADR 002: Run Isolation Forest inside Snowflake

**Status:** Accepted

## Context
The development sandbox does not have scikit-learn, and usage data should not leave Snowflake.

## Decision
Isolation Forest runs as a Snowpark Python stored procedure (`SP_DETECT_ISOLATION_FOREST`,
`sql/09_isolation_forest.sql`) using the scikit-learn package from the Snowflake Anaconda channel.

- Features are log ratios of each daily metric to its trailing 7-day mean, so one model compares all apps.
- `contamination = 0.05` is a generic prior, not tuned to the injected labels (the true anomaly share is ~10%).
- Results go into the same `ANOMALIES` table with `DETECTOR = 'ISOLATION_FOREST'` for a like-for-like benchmark.
- The procedure stages results in a transient table: owner's-rights procedures cannot create temporary tables.

## Consequences
- No data movement; the task graph retrains only when the usage stream has new rows.
- Benchmark result: Isolation Forest reaches better day-level recall than HIGH-only Z-score but more false
  positives (FPR 2.4% vs 0.3%) and misses 2 of 8 scenarios, so Z-score stays the alerting detector and the
  source for incidents.
