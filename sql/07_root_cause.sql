-- 07_root_cause.sql : group anomalies into incidents and assign a deterministic root cause

CREATE TABLE IF NOT EXISTS AI_FINOPS.DETECTION.INCIDENTS (
    INCIDENT_ID        VARCHAR,       -- MD5(source|application|start_date), stable across reruns
    SOURCE             VARCHAR,
    APPLICATION        VARCHAR,
    START_DATE         DATE,
    END_DATE           DATE,
    FLAGGED_DAYS       NUMBER,
    MAX_SEVERITY       VARCHAR,
    MAX_ABS_Z          FLOAT,
    FLAGGED_METRICS    ARRAY,
    BASELINE_CREDITS   FLOAT,         -- avg daily credits in the 7 days before START_DATE
    OBSERVED_CREDITS   FLOAT,         -- avg daily credits over the incident
    EXCESS_CREDITS     FLOAT,         -- total credits above baseline over the incident
    ROOT_CAUSE         VARCHAR,
    CONFIDENCE         FLOAT,
    EVIDENCE           VARIANT,
    UPDATED_AT         TIMESTAMP_LTZ
);

CREATE OR REPLACE VIEW AI_FINOPS.DETECTION.V_INCIDENT_CANDIDATES AS
WITH FLAG_DAYS AS (
    SELECT SOURCE, APPLICATION, USAGE_DATE,
           MAX(IFF(SEVERITY = 'HIGH', 1, 0))   AS HAS_HIGH,
           MAX(ABS(Z_SCORE))                    AS MAX_ABS_Z,
           ARRAY_AGG(DISTINCT METRIC)           AS METRICS
    FROM AI_FINOPS.DETECTION.ANOMALIES
    WHERE DETECTOR = 'ZSCORE_7D'
    GROUP BY 1, 2, 3
),
ISLANDS AS (   -- consecutive flagged days form one island
    SELECT *, DATEADD('DAY', -ROW_NUMBER() OVER (PARTITION BY SOURCE, APPLICATION ORDER BY USAGE_DATE),
                      USAGE_DATE) AS ISLAND
    FROM FLAG_DAYS
),
ISLANDS_H AS (
    SELECT *, MIN(IFF(HAS_HIGH = 1, USAGE_DATE, NULL))
                  OVER (PARTITION BY SOURCE, APPLICATION, ISLAND) AS FIRST_HIGH
    FROM ISLANDS
),
INC AS (
    -- an incident starts at its first HIGH day; leading WARNING-only days are treated as precursors
    SELECT SOURCE, APPLICATION, MIN(USAGE_DATE) AS START_DATE, MAX(USAGE_DATE) AS END_DATE,
           COUNT(*) AS FLAGGED_DAYS, MAX(HAS_HIGH) AS HAS_HIGH, MAX(MAX_ABS_Z) AS MAX_ABS_Z,
           ARRAY_UNION_AGG(METRICS) AS FLAGGED_METRICS
    FROM ISLANDS_H
    WHERE USAGE_DATE >= FIRST_HIGH  -- also drops WARNING-only islands (FIRST_HIGH is NULL)
    GROUP BY SOURCE, APPLICATION, ISLAND
),
CMP AS (
    SELECT I.*,
        AVG(IFF(D.USAGE_DATE <  I.START_DATE, D.CREDITS, NULL))                   AS B_CREDITS,
        AVG(IFF(D.USAGE_DATE >= I.START_DATE, D.CREDITS, NULL))                   AS O_CREDITS,
        SUM(IFF(D.USAGE_DATE >= I.START_DATE, D.CREDITS, 0))                      AS O_CREDITS_SUM,
        AVG(IFF(D.USAGE_DATE <  I.START_DATE, D.REQUESTS, NULL))                  AS B_REQ,
        AVG(IFF(D.USAGE_DATE >= I.START_DATE, D.REQUESTS, NULL))                  AS O_REQ,
        AVG(IFF(D.USAGE_DATE <  I.START_DATE, D.INPUT_TOKENS_PER_REQUEST, NULL))  AS B_IN_TPR,
        AVG(IFF(D.USAGE_DATE >= I.START_DATE, D.INPUT_TOKENS_PER_REQUEST, NULL))  AS O_IN_TPR,
        AVG(IFF(D.USAGE_DATE <  I.START_DATE, D.OUTPUT_TOKENS_PER_REQUEST, NULL)) AS B_OUT_TPR,
        AVG(IFF(D.USAGE_DATE >= I.START_DATE, D.OUTPUT_TOKENS_PER_REQUEST, NULL)) AS O_OUT_TPR,
        AVG(IFF(D.USAGE_DATE <  I.START_DATE, D.RETRY_RATIO, NULL))               AS B_RETRY,
        AVG(IFF(D.USAGE_DATE >= I.START_DATE, D.RETRY_RATIO, NULL))               AS O_RETRY,
        AVG(IFF(D.USAGE_DATE <  I.START_DATE, D.RAG_TOP_K, NULL))                 AS B_TOP_K,
        AVG(IFF(D.USAGE_DATE >= I.START_DATE, D.RAG_TOP_K, NULL))                 AS O_TOP_K,
        MODE(IFF(D.USAGE_DATE <  I.START_DATE, D.PRIMARY_MODEL, NULL))            AS B_MODEL,
        MODE(IFF(D.USAGE_DATE >= I.START_DATE, D.PRIMARY_MODEL, NULL))            AS O_MODEL,
        AVG(IFF(D.USAGE_DATE <  I.START_DATE, D.DUPLICATE_RATIO, NULL))           AS B_DUP,
        AVG(IFF(D.USAGE_DATE >= I.START_DATE, D.DUPLICATE_RATIO, NULL))           AS O_DUP,
        AVG(IFF(D.USAGE_DATE <  I.START_DATE, D.AVG_AGENT_STEPS, NULL))           AS B_STEPS,
        AVG(IFF(D.USAGE_DATE >= I.START_DATE, D.AVG_AGENT_STEPS, NULL))           AS O_STEPS,
        AVG(IFF(D.USAGE_DATE <  I.START_DATE, D.STATIC_CONTEXT_RATIO, NULL))      AS B_STATIC,
        AVG(IFF(D.USAGE_DATE >= I.START_DATE, D.STATIC_CONTEXT_RATIO, NULL))      AS O_STATIC
    FROM INC I
    JOIN AI_FINOPS.ANALYTICS.DAILY_METRICS D
      ON D.SOURCE = I.SOURCE AND D.APPLICATION = I.APPLICATION
     AND D.USAGE_DATE BETWEEN DATEADD('DAY', -7, I.START_DATE) AND I.END_DATE
    GROUP BY ALL
),
RATIOS AS (
    SELECT *,
        O_REQ     / NULLIF(B_REQ, 0)     AS REQ_GROWTH,
        O_IN_TPR  / NULLIF(B_IN_TPR, 0)  AS IN_TPR_GROWTH,
        O_OUT_TPR / NULLIF(B_OUT_TPR, 0) AS OUT_TPR_GROWTH,
        O_TOP_K   / NULLIF(B_TOP_K, 0)   AS TOP_K_GROWTH,
        COALESCE(B_MODEL <> O_MODEL, FALSE) AS MODEL_CHANGED,
        COALESCE(O_STEPS / NULLIF(B_STEPS, 0), 1) AS STEPS_GROWTH,
        -- growth with the explained parts factored out (agent steps, static prefix, duplicates)
        (O_REQ * (1 - COALESCE(O_DUP, 0))) / NULLIF(B_REQ * (1 - COALESCE(B_DUP, 0)), 0)       AS UNIQUE_REQ_GROWTH,
        (O_IN_TPR * (1 - COALESCE(O_STATIC, 0))) / NULLIF(B_IN_TPR * (1 - COALESCE(B_STATIC, 0)), 0)
            / STEPS_GROWTH                                                                     AS DYN_IN_GROWTH,
        (O_IN_TPR * O_STATIC) / NULLIF(B_IN_TPR * B_STATIC, 0) / STEPS_GROWTH                  AS STATIC_TPR_GROWTH,
        OUT_TPR_GROWTH / STEPS_GROWTH                                                          AS OUT_PER_STEP_GROWTH
    FROM CMP
),
DRIVERS AS (
    SELECT *,
        COALESCE(O_DUP >= 0.20 AND O_DUP >= 2 * B_DUP, FALSE) AS D_DUP,
        STEPS_GROWTH >= 2                                    AS D_STEPS,
        COALESCE(UNIQUE_REQ_GROWTH >= 1.5, FALSE)            AS D_REQ,
        COALESCE(STATIC_TPR_GROWTH >= 1.5, FALSE)            AS D_STATIC,
        COALESCE(DYN_IN_GROWTH >= 1.5, FALSE)                AS D_IN,
        COALESCE(OUT_PER_STEP_GROWTH >= 1.5, FALSE)          AS D_OUT
    FROM RATIOS
)
-- Rule order mirrors root_cause/rules.py; first match wins
SELECT *,
    CASE
        WHEN O_RETRY >= 0.20 AND REQ_GROWTH >= 1.5             THEN 'RETRY_LOOP'
        WHEN D_DUP                                             THEN 'DUPLICATE_REQUESTS'
        WHEN D_STEPS                                           THEN 'AGENT_LOOP'
        WHEN REQ_GROWTH >= 2                                   THEN 'REQUEST_VOLUME_SPIKE'
        WHEN MODEL_CHANGED                                     THEN 'MODEL_ROUTING_CHANGE'
        WHEN D_STATIC AND IN_TPR_GROWTH >= 1.5                 THEN 'REPEATED_CONTEXT'
        WHEN D_IN AND TOP_K_GROWTH > 1                         THEN 'RAG_OVER_RETRIEVAL'
        WHEN D_IN                                              THEN 'PROMPT_INFLATION'
        WHEN D_OUT                                             THEN 'OUTPUT_INFLATION'
        ELSE 'UNKNOWN'
    END AS ROOT_CAUSE,
    -- number of independent drivers; >1 means a mixed cause and lower confidence
    (IFF(D_REQ, 1, 0) + IFF(D_DUP, 1, 0) + IFF(D_STEPS, 1, 0) + IFF(MODEL_CHANGED, 1, 0)
     + IFF(D_STATIC, 1, 0) + IFF(D_IN, 1, 0) + IFF(D_OUT, 1, 0)) AS DRIVER_COUNT,
    CASE WHEN ROOT_CAUSE = 'UNKNOWN' THEN 0.30
         WHEN DRIVER_COUNT > 1       THEN 0.60
         WHEN MAX_ABS_Z >= 5         THEN 0.95
         ELSE 0.80 END AS CONFIDENCE
FROM DRIVERS;

CREATE OR REPLACE PROCEDURE AI_FINOPS.DETECTION.SP_BUILD_INCIDENTS()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
    MERGE INTO AI_FINOPS.DETECTION.INCIDENTS T
    USING (
        SELECT
            MD5(SOURCE || '|' || APPLICATION || '|' || START_DATE) AS INCIDENT_ID,
            SOURCE, APPLICATION, START_DATE, END_DATE, FLAGGED_DAYS,
            IFF(HAS_HIGH = 1, 'HIGH', 'WARNING') AS MAX_SEVERITY, MAX_ABS_Z, FLAGGED_METRICS,
            B_CREDITS, O_CREDITS,
            GREATEST(O_CREDITS_SUM - B_CREDITS * FLAGGED_DAYS, 0) AS EXCESS_CREDITS,
            ROOT_CAUSE, CONFIDENCE,
            OBJECT_CONSTRUCT(
                'baseline_window_days', 7,
                'credits',            OBJECT_CONSTRUCT('baseline', ROUND(B_CREDITS, 3), 'observed', ROUND(O_CREDITS, 3)),
                'requests_per_day',   OBJECT_CONSTRUCT('baseline', ROUND(B_REQ), 'observed', ROUND(O_REQ), 'growth', ROUND(REQ_GROWTH, 2)),
                'input_tokens_per_request',  OBJECT_CONSTRUCT('baseline', ROUND(B_IN_TPR), 'observed', ROUND(O_IN_TPR), 'growth', ROUND(IN_TPR_GROWTH, 2)),
                'output_tokens_per_request', OBJECT_CONSTRUCT('baseline', ROUND(B_OUT_TPR), 'observed', ROUND(O_OUT_TPR), 'growth', ROUND(OUT_TPR_GROWTH, 2)),
                'retry_ratio',        OBJECT_CONSTRUCT('baseline', ROUND(B_RETRY, 3), 'observed', ROUND(O_RETRY, 3)),
                'rag_top_k',          OBJECT_CONSTRUCT('baseline', B_TOP_K, 'observed', O_TOP_K),
                'model',              OBJECT_CONSTRUCT('baseline', B_MODEL, 'observed', O_MODEL, 'changed', MODEL_CHANGED),
                'duplicate_ratio',    OBJECT_CONSTRUCT('baseline', ROUND(B_DUP, 3), 'observed', ROUND(O_DUP, 3)),
                'agent_steps_per_request', OBJECT_CONSTRUCT('baseline', ROUND(B_STEPS, 2), 'observed', ROUND(O_STEPS, 2), 'growth', ROUND(STEPS_GROWTH, 2)),
                'static_context_ratio',    OBJECT_CONSTRUCT('baseline', ROUND(B_STATIC, 3), 'observed', ROUND(O_STATIC, 3), 'static_tokens_growth', ROUND(STATIC_TPR_GROWTH, 2)),
                'dynamic_input_growth_per_step', ROUND(DYN_IN_GROWTH, 2),
                'unique_request_growth',   ROUND(UNIQUE_REQ_GROWTH, 2),
                'driver_count',       DRIVER_COUNT
            ) AS EVIDENCE
        FROM AI_FINOPS.DETECTION.V_INCIDENT_CANDIDATES
    ) S
    ON T.INCIDENT_ID = S.INCIDENT_ID
    WHEN MATCHED THEN UPDATE SET
        END_DATE = S.END_DATE, FLAGGED_DAYS = S.FLAGGED_DAYS, MAX_SEVERITY = S.MAX_SEVERITY,
        MAX_ABS_Z = S.MAX_ABS_Z, FLAGGED_METRICS = S.FLAGGED_METRICS,
        BASELINE_CREDITS = S.B_CREDITS, OBSERVED_CREDITS = S.O_CREDITS, EXCESS_CREDITS = S.EXCESS_CREDITS,
        ROOT_CAUSE = S.ROOT_CAUSE, CONFIDENCE = S.CONFIDENCE, EVIDENCE = S.EVIDENCE,
        UPDATED_AT = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT VALUES (
        S.INCIDENT_ID, S.SOURCE, S.APPLICATION, S.START_DATE, S.END_DATE, S.FLAGGED_DAYS,
        S.MAX_SEVERITY, S.MAX_ABS_Z, S.FLAGGED_METRICS, S.B_CREDITS, S.O_CREDITS, S.EXCESS_CREDITS,
        S.ROOT_CAUSE, S.CONFIDENCE, S.EVIDENCE, CURRENT_TIMESTAMP());
    RETURN 'merged ' || SQLROWCOUNT || ' incidents';
END;
$$;
