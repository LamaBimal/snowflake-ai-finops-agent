-- 09_isolation_forest.sql : multivariate Isolation Forest detector (Snowpark Python, scikit-learn)
-- Python logic mirrored in anomaly_detection/isolation_forest.py

-- Features: log ratio of each metric to its trailing 7-day mean (scale-free, comparable across apps)
CREATE OR REPLACE VIEW AI_FINOPS.DETECTION.V_IF_FEATURES AS
SELECT *
FROM (
    SELECT USAGE_DATE, SOURCE, APPLICATION, METRIC,
           LN(GREATEST(VALUE, 1e-9) / GREATEST(BASELINE_AVG, 1e-9)) AS LOG_RATIO
    FROM AI_FINOPS.DETECTION.V_ZSCORE
    WHERE BASELINE_DAYS >= 5
)
PIVOT (MAX(LOG_RATIO) FOR METRIC IN (
    'CREDITS', 'TOTAL_TOKENS', 'REQUESTS',
    'INPUT_TOKENS_PER_REQUEST', 'OUTPUT_TOKENS_PER_REQUEST', 'CREDITS_PER_REQUEST',
    'DUPLICATE_RATIO', 'AVG_AGENT_STEPS', 'STATIC_CONTEXT_RATIO'))
AS P (USAGE_DATE, SOURCE, APPLICATION, CREDITS, TOTAL_TOKENS, REQUESTS,
      INPUT_TOKENS_PER_REQUEST, OUTPUT_TOKENS_PER_REQUEST, CREDITS_PER_REQUEST,
      DUPLICATE_RATIO, AVG_AGENT_STEPS, STATIC_CONTEXT_RATIO);

CREATE OR REPLACE PROCEDURE AI_FINOPS.DETECTION.SP_DETECT_ISOLATION_FOREST(
    CONTAMINATION FLOAT, MIN_ROWS NUMBER)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'scikit-learn', 'pandas', 'numpy')
HANDLER = 'run'
AS
$$
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

FEATURES = ["CREDITS", "TOTAL_TOKENS", "REQUESTS",
            "INPUT_TOKENS_PER_REQUEST", "OUTPUT_TOKENS_PER_REQUEST", "CREDITS_PER_REQUEST",
            "DUPLICATE_RATIO", "AVG_AGENT_STEPS", "STATIC_CONTEXT_RATIO"]


def run(session, contamination, min_rows):
    feats = session.table("AI_FINOPS.DETECTION.V_IF_FEATURES").to_pandas()
    out = []
    for source, df in feats.groupby("SOURCE"):
        if len(df) < min_rows:
            continue
        X = df[FEATURES].astype(float).fillna(0.0).to_numpy()
        model = IsolationForest(n_estimators=300, contamination=contamination, random_state=42)
        model.fit(X)
        score = -model.score_samples(X)              # higher = more anomalous
        high_cut = np.quantile(score, 1 - contamination)
        warn_cut = np.quantile(score, 1 - 2 * contamination)
        # metric with the largest absolute log ratio explains the flag
        top_metric = np.array(FEATURES)[np.abs(X).argmax(axis=1)]
        top_ratio = X[np.arange(len(X)), np.abs(X).argmax(axis=1)]
        res = pd.DataFrame({
            "USAGE_DATE": df.USAGE_DATE.values,
            "SOURCE": source,
            "APPLICATION": df.APPLICATION.values,
            "METRIC": top_metric,
            "PCT_CHANGE": np.exp(top_ratio) - 1,
            "Z_SCORE": score,                        # anomaly score, not a z-score
            "SEVERITY": np.where(score >= high_cut, "HIGH", np.where(score >= warn_cut, "WARNING", "NORMAL")),
        })
        out.append(res[res.SEVERITY != "NORMAL"])

    session.sql("DELETE FROM AI_FINOPS.DETECTION.ANOMALIES WHERE DETECTOR = 'ISOLATION_FOREST'").collect()
    if not out:
        return "no source had enough rows"
    res = pd.concat(out, ignore_index=True)
    res["USAGE_DATE"] = pd.to_datetime(res["USAGE_DATE"]).dt.date
    session.create_dataframe(res).write.save_as_table(
        "AI_FINOPS.DETECTION.IF_STAGING", mode="overwrite", table_type="transient")
    session.sql("""
        INSERT INTO AI_FINOPS.DETECTION.ANOMALIES
            (USAGE_DATE, SOURCE, APPLICATION, METRIC, PCT_CHANGE, Z_SCORE, SEVERITY, DETECTOR)
        SELECT USAGE_DATE, SOURCE, APPLICATION, METRIC, PCT_CHANGE, Z_SCORE, SEVERITY, 'ISOLATION_FOREST'
        FROM AI_FINOPS.DETECTION.IF_STAGING""").collect()
    return f"isolation forest flagged {len(res)} app-days"
$$;
