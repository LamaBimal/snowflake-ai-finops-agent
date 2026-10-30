"""Response-quality evaluation for the model-routing experiment: per-model, per-class accuracy
and the most common confusions. Reads DETECTION.ROUTING_PREDICTIONS.
Run: python3 evaluation/quality_evaluation.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.snowflake_session import get_session  # noqa: E402


def main():
    s = get_session()
    per_class = s.sql("""
        SELECT MODEL_NAME, LABEL, ROUND(AVG(IFF(PREDICTION = LABEL, 1, 0)), 2) AS ACC
        FROM AI_FINOPS.DETECTION.ROUTING_PREDICTIONS GROUP BY 1, 2""").to_pandas()
    print(per_class.pivot(index="LABEL", columns="MODEL_NAME", values="ACC").to_string())

    errors = s.sql("""
        SELECT P.MODEL_NAME, P.LABEL, P.PREDICTION, E.TICKET_TEXT
        FROM AI_FINOPS.DETECTION.ROUTING_PREDICTIONS P
        JOIN AI_FINOPS.RAW.ROUTING_EVAL_SET E USING (TICKET_ID)
        WHERE P.PREDICTION IS DISTINCT FROM P.LABEL
        ORDER BY 1, 2""").to_pandas()
    print(f"\n{len(errors)} misclassifications")
    print(errors.to_string(index=False, max_colwidth=70))


if __name__ == "__main__":
    main()
