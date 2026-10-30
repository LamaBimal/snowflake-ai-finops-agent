-- 06_tasks.sql : daily detection run (created SUSPENDED; resume when ready)
CREATE OR REPLACE TASK AI_FINOPS.DETECTION.TASK_DAILY_DETECTION
    WAREHOUSE = COMPUTE_WH
    SCHEDULE = 'USING CRON 0 6 * * * UTC'   -- ACCOUNT_USAGE lags up to a few hours
    COMMENT = 'Daily Z-score AI cost anomaly detection'
AS
    CALL AI_FINOPS.DETECTION.SP_DETECT_ANOMALIES(3);

-- To enable:
-- ALTER TASK AI_FINOPS.DETECTION.TASK_DAILY_DETECTION RESUME;
