-- 11_agent_search_usage.sql : Cortex Agent + Cortex Search usage, plus latency / failure for AI functions
-- Run after 02_usage_view.sql; 03_usage_metrics.sql unions these views into AI_USAGE_METRICS.
-- Column order must match V_CORTEX_USAGE.

-- Cortex Agents: one row per agent request; tokens summed across tool/model calls
CREATE OR REPLACE VIEW AI_FINOPS.ANALYTICS.V_CORTEX_AGENT_USAGE AS
WITH G AS (
    SELECT H.REQUEST_ID,
           SUM(COALESCE(F.VALUE:input::NUMBER, 0) + COALESCE(F.VALUE:cache_read_input::NUMBER, 0)
               + COALESCE(F.VALUE:cache_write_input::NUMBER, 0))          AS INPUT_TOKENS,
           SUM(COALESCE(F.VALUE:output::NUMBER, 0))                        AS OUTPUT_TOKENS,
           SUM(COALESCE(F.VALUE:cache_read_input::NUMBER, 0))              AS CACHE_READ_TOKENS,
           COUNT(*)                                                        AS STEPS,
           MODE(F.VALUE:model::STRING)                                     AS MODEL_NAME
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY H,
         LATERAL FLATTEN(INPUT => H.TOKENS_GRANULAR, OUTER => TRUE) F
    GROUP BY 1
)
SELECT
    H.START_TIME                                                   AS USAGE_TIME,
    H.REQUEST_ID                                                   AS QUERY_ID,
    'agent:' || H.AGENT_DATABASE_NAME || '.' || H.AGENT_SCHEMA_NAME || '.' || H.AGENT_NAME AS APPLICATION,
    H.USER_ID::STRING                                              AS USER_ID,
    H.METADATA:role_name::STRING                                   AS ROLE_NAME,
    'CORTEX_AGENT'                                                 AS FUNCTION_NAME,
    COALESCE(G.MODEL_NAME, 'unknown')                              AS MODEL_NAME,
    COALESCE(G.INPUT_TOKENS, H.TOKENS)                             AS INPUT_TOKENS,
    COALESCE(G.OUTPUT_TOKENS, 0)                                   AS OUTPUT_TOKENS,
    H.TOKEN_CREDITS::FLOAT                                         AS CREDITS,
    1                                                              AS REQUEST_COUNT,
    0                                                              AS RETRY_COUNT,
    NULL::NUMBER                                                   AS RAG_TOP_K,
    NULL::NUMBER                                                   AS DUPLICATE_COUNT,
    COALESCE(G.STEPS, 1)                                           AS AGENT_STEPS,
    G.CACHE_READ_TOKENS                                            AS CACHEABLE_INPUT_TOKENS,
    DATEDIFF('MILLISECOND', H.START_TIME, H.END_TIME)              AS LATENCY_MS,
    0                                                              AS FAILED_COUNT
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY H
LEFT JOIN G USING (REQUEST_ID);

-- Cortex Search: daily per service (no per-request rows, so no latency / request counts)
CREATE OR REPLACE VIEW AI_FINOPS.ANALYTICS.V_CORTEX_SEARCH_USAGE AS
SELECT
    USAGE_DATE                                                     AS USAGE_TIME,
    NULL::STRING                                                   AS QUERY_ID,
    'search:' || DATABASE_NAME || '.' || SCHEMA_NAME || '.' || SERVICE_NAME AS APPLICATION,
    NULL::STRING                                                   AS USER_ID,
    NULL::STRING                                                   AS ROLE_NAME,
    'CORTEX_SEARCH_' || CONSUMPTION_TYPE                           AS FUNCTION_NAME,
    COALESCE(MODEL_NAME, 'n/a')                                    AS MODEL_NAME,
    COALESCE(TOKENS, 0)                                            AS INPUT_TOKENS,
    0                                                              AS OUTPUT_TOKENS,
    CREDITS::FLOAT                                                 AS CREDITS,
    NULL::NUMBER                                                   AS REQUEST_COUNT,
    NULL::NUMBER                                                   AS RETRY_COUNT,
    NULL::NUMBER                                                   AS RAG_TOP_K,
    NULL::NUMBER                                                   AS DUPLICATE_COUNT,
    NULL::NUMBER                                                   AS AGENT_STEPS,
    NULL::NUMBER                                                   AS CACHEABLE_INPUT_TOKENS,
    NULL::NUMBER                                                   AS LATENCY_MS,
    NULL::NUMBER                                                   AS FAILED_COUNT
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY;
