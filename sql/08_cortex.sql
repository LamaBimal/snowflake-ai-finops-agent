-- 08_cortex.sql : recommendation playbook + Cortex-generated incident explanations
-- Prompt template mirrored in agent/prompts/explain_incident.txt

CREATE OR REPLACE TABLE AI_FINOPS.DETECTION.RECOMMENDATION_PLAYBOOK (
    ROOT_CAUSE      VARCHAR,
    ACTION          VARCHAR,
    SAVING_PCT_LOW  FLOAT,
    SAVING_PCT_HIGH FLOAT,
    QUALITY_RISK    VARCHAR
);

INSERT INTO AI_FINOPS.DETECTION.RECOMMENDATION_PLAYBOOK VALUES
    ('PROMPT_INFLATION',     'Trim conversation history and system prompt; cache static context; cap input tokens per request.', 0.30, 0.60, 'LOW_TO_MEDIUM'),
    ('RAG_OVER_RETRIEVAL',   'Reduce retrieval top_k back toward 5-8 and add a reranker / relevance threshold.',               0.30, 0.45, 'LOW_TO_MEDIUM'),
    ('OUTPUT_INFLATION',     'Set max_tokens (e.g. 2000 -> 800) and instruct concise output format.',                            0.15, 0.35, 'LOW'),
    ('MODEL_ROUTING_CHANGE', 'Route this task back to the smaller model; gate large-model use behind a quality check.',          0.60, 0.95, 'LOW_TO_MEDIUM'),
    ('RETRY_LOOP',           'Add capped retries with exponential backoff and idempotency keys; alert on retry ratio > 20%.',   0.60, 0.80, 'LOW'),
    ('REQUEST_VOLUME_SPIKE', 'Confirm whether traffic is organic; add request caching / dedup and per-app rate limits.',        0.10, 0.40, 'LOW'),
    ('DUPLICATE_REQUESTS',   'Add a response cache keyed on the request fingerprint (template + inputs) with a short TTL.',     0.25, 0.35, 'LOW'),
    ('AGENT_LOOP',           'Cap agent iterations (e.g. max 4 steps), add a stop condition and loop detection on repeated tool calls.', 0.60, 0.80, 'LOW_TO_MEDIUM'),
    ('REPEATED_CONTEXT',     'Move the static prefix into a cached/reused context (prompt caching or retrieval by reference) instead of resending it.', 0.40, 0.65, 'LOW'),
    ('UNKNOWN',              'Investigate manually; no single driver explains the change.',                                       0.00, 0.00, 'UNKNOWN');

CREATE TABLE IF NOT EXISTS AI_FINOPS.DETECTION.INCIDENT_EXPLANATIONS (
    INCIDENT_ID             VARCHAR,
    MODEL_NAME              VARCHAR,
    EXPLANATION             VARIANT,      -- structured output from AI_COMPLETE
    EST_SAVING_CREDITS_LOW  FLOAT,        -- deterministic: excess credits * playbook %
    EST_SAVING_CREDITS_HIGH FLOAT,
    PROMPT_TOKENS           NUMBER,
    COMPLETION_TOKENS       NUMBER,
    GENERATED_AT            TIMESTAMP_LTZ
);

-- Explains incidents that have no explanation yet (or all when FORCE = TRUE)
CREATE OR REPLACE PROCEDURE AI_FINOPS.DETECTION.SP_EXPLAIN_INCIDENTS(FORCE BOOLEAN)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
    IF (:FORCE) THEN
        DELETE FROM AI_FINOPS.DETECTION.INCIDENT_EXPLANATIONS;
    END IF;

    INSERT INTO AI_FINOPS.DETECTION.INCIDENT_EXPLANATIONS
    WITH TODO AS (
        SELECT I.*, P.ACTION, P.SAVING_PCT_LOW, P.SAVING_PCT_HIGH, P.QUALITY_RISK
        FROM AI_FINOPS.DETECTION.INCIDENTS I
        JOIN AI_FINOPS.DETECTION.RECOMMENDATION_PLAYBOOK P ON P.ROOT_CAUSE = I.ROOT_CAUSE
        WHERE I.INCIDENT_ID NOT IN (SELECT INCIDENT_ID FROM AI_FINOPS.DETECTION.INCIDENT_EXPLANATIONS)
    ),
    RESP AS (
        SELECT T.*,
            AI_COMPLETE(
                model => 'llama3.1-70b',
                prompt => CONCAT(
                    'You are an AI FinOps analyst. Explain a detected AI cost incident to an engineering team.\n',
                    'Rules:\n- Use ONLY the numbers in <evidence> and <playbook>. Never invent metrics, percentages, or causes.\n',
                    '- The root cause was determined by deterministic rules: "', ROOT_CAUSE, '". Do not change it.\n',
                    '- Quote baseline vs observed values when describing evidence.\n',
                    '- Keep the recommendation concrete and aligned with the playbook action.\n',
                    '- estimated_saving must restate the playbook saving range; do not compute new numbers.\n\n',
                    '<incident>\napplication: ', APPLICATION,
                    '\nperiod: ', START_DATE, ' to ', END_DATE, ' (', FLAGGED_DAYS, ' flagged days)',
                    '\nseverity: ', MAX_SEVERITY, ', max |z| = ', ROUND(MAX_ABS_Z, 1),
                    '\nbaseline credits/day: ', ROUND(BASELINE_CREDITS, 2),
                    '; observed credits/day: ', ROUND(OBSERVED_CREDITS, 2),
                    '\nexcess credits: ', ROUND(EXCESS_CREDITS, 2), '\n</incident>\n\n',
                    '<evidence>\n', EVIDENCE::STRING, '\n</evidence>\n\n',
                    '<playbook>\n', OBJECT_CONSTRUCT('action', ACTION,
                        'saving_range', CONCAT(ROUND(SAVING_PCT_LOW * 100), '-', ROUND(SAVING_PCT_HIGH * 100), '%'),
                        'quality_risk', QUALITY_RISK)::STRING, '\n</playbook>\n\n',
                    'Return JSON with: problem, evidence (array of short strings), recommendation, ',
                    'estimated_saving, quality_risk, confidence.'),
                model_parameters => {'temperature': 0, 'max_tokens': 800},
                response_format => {
                    'type': 'json',
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'problem':          {'type': 'string'},
                            'evidence':         {'type': 'array', 'items': {'type': 'string'}},
                            'recommendation':   {'type': 'string'},
                            'estimated_saving': {'type': 'string'},
                            'quality_risk':     {'type': 'string'},
                            'confidence':       {'type': 'string'}
                        },
                        'required': ['problem', 'evidence', 'recommendation',
                                     'estimated_saving', 'quality_risk', 'confidence']
                    }
                },
                show_details => TRUE
            ) AS R
        FROM TODO T
    )
    SELECT
        INCIDENT_ID,
        'llama3.1-70b',
        R:structured_output[0]:raw_message,
        EXCESS_CREDITS * SAVING_PCT_LOW,
        EXCESS_CREDITS * SAVING_PCT_HIGH,
        R:usage:prompt_tokens::NUMBER,
        R:usage:completion_tokens::NUMBER,
        CURRENT_TIMESTAMP()
    FROM RESP;

    RETURN 'explained ' || SQLROWCOUNT || ' incidents';
END;
$$;

-- Dashboard-friendly view
CREATE OR REPLACE VIEW AI_FINOPS.DETECTION.V_INCIDENT_REPORT AS
SELECT
    I.INCIDENT_ID, I.SOURCE, I.APPLICATION, I.START_DATE, I.END_DATE, I.FLAGGED_DAYS,
    I.MAX_SEVERITY, I.MAX_ABS_Z, I.ROOT_CAUSE, I.CONFIDENCE,
    I.BASELINE_CREDITS, I.OBSERVED_CREDITS, I.EXCESS_CREDITS, I.EVIDENCE,
    P.ACTION AS PLAYBOOK_ACTION, P.QUALITY_RISK,
    E.EST_SAVING_CREDITS_LOW, E.EST_SAVING_CREDITS_HIGH,
    E.EXPLANATION:problem::STRING          AS AI_PROBLEM,
    E.EXPLANATION:evidence                 AS AI_EVIDENCE,
    E.EXPLANATION:recommendation::STRING   AS AI_RECOMMENDATION,
    E.EXPLANATION:estimated_saving::STRING AS AI_ESTIMATED_SAVING,
    E.GENERATED_AT
FROM AI_FINOPS.DETECTION.INCIDENTS I
LEFT JOIN AI_FINOPS.DETECTION.RECOMMENDATION_PLAYBOOK P ON P.ROOT_CAUSE = I.ROOT_CAUSE
LEFT JOIN AI_FINOPS.DETECTION.INCIDENT_EXPLANATIONS E ON E.INCIDENT_ID = I.INCIDENT_ID;
