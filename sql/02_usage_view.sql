-- 02_usage_view.sql : normalize real Cortex AI usage telemetry
CREATE OR REPLACE VIEW AI_FINOPS.ANALYTICS.V_CORTEX_USAGE AS
WITH M AS (
    SELECT
        H.START_TIME,
        H.QUERY_ID,
        H.QUERY_TAG,
        H.USER_ID,
        H.ROLE_NAMES,
        H.FUNCTION_NAME,
        H.MODEL_NAME,
        H.CREDITS,
        H.END_TIME,
        H.IS_COMPLETED,
        SUM(IFF(F.VALUE:key:metric::STRING = 'input',  F.VALUE:value::NUMBER, 0)) AS INPUT_TOKENS,
        SUM(IFF(F.VALUE:key:metric::STRING = 'output', F.VALUE:value::NUMBER, 0)) AS OUTPUT_TOKENS,
        SUM(IFF(F.VALUE:key:metric::STRING = 'total',  F.VALUE:value::NUMBER, 0)) AS TOTAL_ONLY_TOKENS
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY H,
         LATERAL FLATTEN(INPUT => H.METRICS, OUTER => TRUE) F
    GROUP BY ALL
)
SELECT
    START_TIME                                         AS USAGE_TIME,
    QUERY_ID,
    -- plain-string tags ('rag-support-agent') or JSON tags ({"app": "..."})
    COALESCE(TRY_PARSE_JSON(QUERY_TAG):app::STRING, NULLIF(QUERY_TAG, ''), 'untagged') AS APPLICATION,
    USER_ID::STRING                                    AS USER_ID,
    ROLE_NAMES[0]::STRING                              AS ROLE_NAME,
    FUNCTION_NAME,
    COALESCE(NULLIF(MODEL_NAME, ''), 'default')        AS MODEL_NAME,
    INPUT_TOKENS + IFF(INPUT_TOKENS + OUTPUT_TOKENS = 0, TOTAL_ONLY_TOKENS, 0) AS INPUT_TOKENS,
    OUTPUT_TOKENS,
    CREDITS::FLOAT                                     AS CREDITS,
    1                                                  AS REQUEST_COUNT,
    0                                                  AS RETRY_COUNT,
    NULL::NUMBER                                       AS RAG_TOP_K,
    NULL::NUMBER                                       AS DUPLICATE_COUNT,         -- not in Cortex telemetry
    1                                                  AS AGENT_STEPS,
    NULL::NUMBER                                       AS CACHEABLE_INPUT_TOKENS,
    NULL::NUMBER                                       AS LATENCY_MS,   -- START/END are hourly buckets here, not call timing
    IFF(IS_COMPLETED, 0, 1)                            AS FAILED_COUNT
FROM M;
