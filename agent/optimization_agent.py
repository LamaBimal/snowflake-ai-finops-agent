"""Optimization agent: generate Cortex explanations + recommendations for unexplained incidents.

Run: python3 agent/optimization_agent.py [--force]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.snowflake_session import get_session  # noqa: E402


def main():
    force = "--force" in sys.argv
    s = get_session()
    print(s.sql(f"CALL AI_FINOPS.DETECTION.SP_EXPLAIN_INCIDENTS({str(force).upper()})").collect()[0][0])
    df = s.sql("""SELECT APPLICATION, ROOT_CAUSE, AI_RECOMMENDATION,
                         ROUND(EST_SAVING_CREDITS_LOW, 2) AS SAVE_LO, ROUND(EST_SAVING_CREDITS_HIGH, 2) AS SAVE_HI,
                         QUALITY_RISK
                  FROM AI_FINOPS.DETECTION.V_INCIDENT_REPORT ORDER BY START_DATE""").to_pandas()
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
