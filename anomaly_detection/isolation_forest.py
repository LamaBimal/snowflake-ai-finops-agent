"""Isolation Forest detector driver. The model runs inside Snowflake
(AI_FINOPS.DETECTION.SP_DETECT_ISOLATION_FOREST, sql/09_isolation_forest.sql) because
scikit-learn is provided by the Snowflake Anaconda channel there.

Run: python3 anomaly_detection/isolation_forest.py [contamination]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.snowflake_session import get_session  # noqa: E402


def main():
    contamination = float(sys.argv[1]) if len(sys.argv) > 1 else 0.05
    s = get_session()
    print(s.sql("CALL AI_FINOPS.DETECTION.SP_DETECT_ISOLATION_FOREST(?, 30)", params=[contamination]).collect()[0][0])


if __name__ == "__main__":
    main()
