"""Build a harder, validated ticket set for the model-routing experiment.

1. Generate: llama3.1-70b writes 5 tickets per call, 4 calls per class (20 calls, 100 tickets).
   Each call gets a different persona/product seed; ~30% of tickets are asked to be deliberately
   ambiguous (they mention a second category but the intended one is primary).
2. Validate: claude-sonnet-4-5 labels every ticket independently; tickets where it disagrees with
   the intended label are dropped, so the remaining labels are confirmed by a second model.

Writes RAW.ROUTING_EVAL_CANDIDATES (all) and replaces RAW.ROUTING_EVAL_SET (validated).
Run: python3 model_routing/build_eval_set.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.snowflake_session import get_session  # noqa: E402
from model_routing.evaluator import LABELS, PROMPT  # noqa: E402

DESCRIPTIONS = {
    "billing": "charges, invoices, refunds, payment methods, taxes, pricing disputes",
    "technical_issue": "errors, crashes, slowness, integrations or exports not working",
    "account_access": "login, password, 2FA/SSO, locked accounts, user/admin permissions",
    "feature_request": "asking for new functionality or improvements that do not exist yet",
    "cancellation": "ending, not renewing, or closing the subscription/account",
}
SEEDS = [
    ("a frustrated small-business owner", "an invoicing app"),
    ("an IT admin at a 2,000-person company", "a data analytics platform"),
    ("a non-native English speaker writing briefly", "a project management tool"),
    ("a polite finance manager", "an HR and payroll SaaS"),
]


def gen_sql() -> str:
    label_desc = "; ".join(f"{k}: {v}" for k, v in DESCRIPTIONS.items())
    rows = ",\n".join(
        f"('{label}', {i}, '{persona}', '{product}')"
        for label in LABELS for i, (persona, product) in enumerate(SEEDS))
    return f"""
    CREATE OR REPLACE TABLE AI_FINOPS.RAW.ROUTING_EVAL_CANDIDATES AS
    WITH SEEDS (LABEL, SEED, PERSONA, PRODUCT) AS (SELECT * FROM VALUES {rows}),
    GEN AS (
        SELECT LABEL, SEED,
               AI_COMPLETE(
                   model => 'llama3.1-70b',
                   prompt => CONCAT(
                       'Write 5 realistic, varied customer support tickets (1-3 sentences each) from ',
                       PERSONA, ' using ', PRODUCT, '. Every ticket must primarily belong to the category "',
                       LABEL, '". Categories: {label_desc}. ',
                       'Make tickets 4 and 5 deliberately ambiguous: they should also mention a secondary ',
                       'issue from another category, but "', LABEL, '" must remain the main request. ',
                       'Vary wording; do not reuse phrases; do not name the category.'),
                   model_parameters => {{'temperature': 0.9, 'max_tokens': 900}},
                   response_format => {{'type': 'json', 'schema': {{'type': 'object',
                       'properties': {{'tickets': {{'type': 'array', 'items': {{'type': 'string'}}}}}},
                       'required': ['tickets']}}}}) AS R
        FROM SEEDS
    )
    SELECT LABEL || '-' || SEED || '-' || T.INDEX AS TICKET_ID,
           T.VALUE::STRING                         AS TICKET_TEXT,
           LABEL,
           T.INDEX >= 3                            AS IS_AMBIGUOUS
    FROM GEN, LATERAL FLATTEN(INPUT => R:tickets) T
    WHERE T.INDEX < 5 AND LENGTH(T.VALUE::STRING) > 20
    """


def validate_sql() -> str:
    labels = ", ".join(f"'{l}'" for l in LABELS)
    return f"""
    CREATE OR REPLACE TABLE AI_FINOPS.RAW.ROUTING_EVAL_CANDIDATES AS
    SELECT C.*,
           AI_COMPLETE(
               model => 'claude-sonnet-4-5',
               prompt => CONCAT('{PROMPT}', TICKET_TEXT),
               model_parameters => {{'temperature': 0, 'max_tokens': 100}},
               response_format => {{'type': 'json', 'schema': {{'type': 'object',
                   'properties': {{'category': {{'type': 'string', 'enum': [{labels}]}}}},
                   'required': ['category'], 'additionalProperties': false}}}}
           ):category::STRING AS VALIDATOR_LABEL
    FROM AI_FINOPS.RAW.ROUTING_EVAL_CANDIDATES C
    """


def main():
    s = get_session()
    s.sql("ALTER SESSION SET QUERY_TAG = 'routing-eval:build-set'").collect()
    s.sql(gen_sql()).collect()
    s.sql(validate_sql()).collect()
    s.sql("ALTER SESSION UNSET QUERY_TAG").collect()
    s.sql("""CREATE OR REPLACE TABLE AI_FINOPS.RAW.ROUTING_EVAL_SET AS
             SELECT TICKET_ID, TICKET_TEXT, LABEL, IS_AMBIGUOUS
             FROM AI_FINOPS.RAW.ROUTING_EVAL_CANDIDATES
             WHERE VALIDATOR_LABEL = LABEL""").collect()
    print(s.sql("""SELECT COUNT(*) AS GENERATED, COUNT_IF(VALIDATOR_LABEL = LABEL) AS KEPT,
                          COUNT_IF(VALIDATOR_LABEL = LABEL AND IS_AMBIGUOUS) AS KEPT_AMBIGUOUS
                   FROM AI_FINOPS.RAW.ROUTING_EVAL_CANDIDATES""").to_pandas().to_string(index=False))
    print(s.sql("""SELECT LABEL, COUNT(*) AS N FROM AI_FINOPS.RAW.ROUTING_EVAL_SET GROUP BY 1 ORDER BY 1""")
          .to_pandas().to_string(index=False))


if __name__ == "__main__":
    main()
