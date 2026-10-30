"""Model-routing optimizer: cheapest model whose accuracy meets the quality threshold.

  minimize   credits per request
  subject to accuracy >= MIN_ACCURACY

Cost = avg tokens/request (from ROUTING_PREDICTIONS) x credits/token observed for that model in this
account's own Cortex usage history (ANALYTICS.V_CORTEX_USAGE). ACCOUNT_USAGE lags by up to a few
hours, so rates sharpen as the eval calls land there.
Writes DETECTION.MODEL_ROUTING_RESULTS.
Run: python3 model_routing/optimizer.py [min_accuracy]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.snowflake_session import get_session  # noqa: E402

RESULTS_SQL = """
CREATE OR REPLACE TABLE AI_FINOPS.DETECTION.MODEL_ROUTING_RESULTS AS
WITH QUALITY AS (
    SELECT MODEL_NAME,
           COUNT(*)                                    AS N_EVAL,
           AVG(IFF(PREDICTION = LABEL, 1, 0))          AS ACCURACY,
           AVG(PROMPT_TOKENS)                          AS AVG_INPUT_TOKENS,
           AVG(COMPLETION_TOKENS)                      AS AVG_OUTPUT_TOKENS
    FROM AI_FINOPS.DETECTION.ROUTING_PREDICTIONS
    GROUP BY 1
),
RATES AS (   -- blended credits per token actually billed to this account
    SELECT MODEL_NAME,
           COUNT(*)                                                         AS RATE_SOURCE_CALLS,
           SUM(CREDITS) / NULLIF(SUM(INPUT_TOKENS + OUTPUT_TOKENS), 0)      AS CREDITS_PER_TOKEN
    FROM AI_FINOPS.ANALYTICS.V_CORTEX_USAGE
    WHERE FUNCTION_NAME = 'AI_COMPLETE'
    GROUP BY 1
),
J AS (
    SELECT Q.*, R.RATE_SOURCE_CALLS,
           R.CREDITS_PER_TOKEN * 1e6                                                AS CREDITS_PER_M_TOKENS,
           (Q.AVG_INPUT_TOKENS + Q.AVG_OUTPUT_TOKENS) * R.CREDITS_PER_TOKEN * 1000   AS CREDITS_PER_1K_REQUESTS
    FROM QUALITY Q LEFT JOIN RATES R USING (MODEL_NAME)
)
SELECT J.*,
       1 - CREDITS_PER_1K_REQUESTS / MAX(CREDITS_PER_1K_REQUESTS) OVER ()           AS SAVING_VS_LARGEST,
       ACCURACY - MAX(ACCURACY) OVER ()                                              AS ACCURACY_GAP_VS_BEST,
       ACCURACY >= ? AS MEETS_THRESHOLD,
       COALESCE(MEETS_THRESHOLD AND CREDITS_PER_1K_REQUESTS = MIN(IFF(MEETS_THRESHOLD, CREDITS_PER_1K_REQUESTS, NULL)) OVER (), FALSE)
                                                                                     AS RECOMMENDED
FROM J
"""


def main():
    min_acc = float(sys.argv[1]) if len(sys.argv) > 1 else 0.95
    s = get_session()
    s.sql(RESULTS_SQL, params=[min_acc]).collect()
    df = s.sql("""SELECT MODEL_NAME, N_EVAL, ROUND(ACCURACY, 3) AS ACCURACY,
                         ROUND(AVG_INPUT_TOKENS) AS IN_TOK, ROUND(AVG_OUTPUT_TOKENS) AS OUT_TOK,
                         ROUND(CREDITS_PER_M_TOKENS, 3) AS CR_PER_M_TOK, RATE_SOURCE_CALLS,
                         ROUND(CREDITS_PER_1K_REQUESTS, 4) AS CR_PER_1K_REQ,
                         ROUND(SAVING_VS_LARGEST, 3) AS SAVING_VS_LARGEST, RECOMMENDED
                  FROM AI_FINOPS.DETECTION.MODEL_ROUTING_RESULTS
                  ORDER BY CREDITS_PER_1K_REQUESTS""").to_pandas()
    print(f"min accuracy = {min_acc:.0%}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
