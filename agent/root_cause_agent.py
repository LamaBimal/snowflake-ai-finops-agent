"""Root-cause agent: rebuild incidents from detected anomalies and print them.

The root cause itself is deterministic (sql/07_root_cause.sql); this script just drives the pipeline.
Run: python3 agent/root_cause_agent.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.snowflake_session import get_session  # noqa: E402


def main():
    s = get_session()
    print(s.sql("CALL AI_FINOPS.DETECTION.SP_DETECT_ANOMALIES(90)").collect()[0][0])
    print(s.sql("CALL AI_FINOPS.DETECTION.SP_BUILD_INCIDENTS()").collect()[0][0])
    df = s.sql("""SELECT APPLICATION, START_DATE, END_DATE, MAX_SEVERITY, ROOT_CAUSE, CONFIDENCE,
                         ROUND(EXCESS_CREDITS, 2) AS EXCESS_CREDITS
                  FROM AI_FINOPS.DETECTION.INCIDENTS ORDER BY START_DATE""").to_pandas()
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
