"""Evaluate the Z-score detector against injected anomaly labels.

Day-level: an application-day is "predicted anomalous" if any metric reaches the severity threshold.
Event-level: a scenario is detected if any of its days is flagged; delay = days from start to first flag.
Run: python3 anomaly_detection/statistical.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.snowflake_session import get_session  # noqa: E402

DAY_SQL = """
WITH DAYS AS (
    SELECT DISTINCT USAGE_DATE, APPLICATION FROM AI_FINOPS.DETECTION.V_ZSCORE
    WHERE SOURCE = 'SYNTHETIC' AND SEVERITY <> 'INSUFFICIENT_HISTORY'
),
PRED AS (
    SELECT USAGE_DATE, APPLICATION,
           MAX(IFF(SEVERITY = 'HIGH', 1, 0)) AS HIGH_FLAG,
           MAX(IFF(SEVERITY IN ('HIGH', 'WARNING'), 1, 0)) AS ANY_FLAG
    FROM AI_FINOPS.DETECTION.ANOMALIES
    WHERE SOURCE = 'SYNTHETIC' AND DETECTOR = '{detector}' GROUP BY 1, 2
)
SELECT D.USAGE_DATE, D.APPLICATION, L.SCENARIO, L.START_DATE,
       IFF(L.SCENARIO IS NOT NULL, 1, 0) AS ACTUAL,
       COALESCE(P.HIGH_FLAG, 0) AS HIGH_FLAG, COALESCE(P.ANY_FLAG, 0) AS ANY_FLAG
FROM DAYS D
LEFT JOIN AI_FINOPS.RAW.ANOMALY_LABELS L
       ON L.APPLICATION = D.APPLICATION AND D.USAGE_DATE BETWEEN L.START_DATE AND L.END_DATE
LEFT JOIN PRED P ON P.USAGE_DATE = D.USAGE_DATE AND P.APPLICATION = D.APPLICATION
"""


def score(df, flag):
    tp = int(((df[flag] == 1) & (df.ACTUAL == 1)).sum())
    fp = int(((df[flag] == 1) & (df.ACTUAL == 0)).sum())
    fn = int(((df[flag] == 0) & (df.ACTUAL == 1)).sum())
    tn = int(((df[flag] == 0) & (df.ACTUAL == 0)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0

    events = df[df.ACTUAL == 1].groupby("SCENARIO")
    detected, delays = 0, []
    for _, g in events:
        hits = g[g[flag] == 1]
        if len(hits):
            detected += 1
            delays.append((hits.USAGE_DATE.min() - g.START_DATE.iloc[0]).days)
    return dict(threshold=flag, tp=tp, fp=fp, fn=fn, precision=p, recall=r, f1=f1, fpr=fpr,
                events_detected=f"{detected}/{events.ngroups}",
                mean_delay_days=sum(delays) / len(delays) if delays else None)


def load(session, detector="ZSCORE_7D"):
    assert detector in ("ZSCORE_7D", "ISOLATION_FOREST")  # fixed allowlist; value is interpolated
    return session.sql(DAY_SQL.format(detector=detector)).to_pandas()


def main():
    df = load(get_session())
    for flag in ("HIGH_FLAG", "ANY_FLAG"):
        s = score(df, flag)
        print(" | ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in s.items()))


if __name__ == "__main__":
    main()
