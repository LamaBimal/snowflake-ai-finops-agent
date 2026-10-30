"""Model-routing evaluator: classify labeled support tickets with several Cortex models.

Builds RAW.ROUTING_EVAL_SET (60 synthetic labeled tickets, 5 classes), then for each model writes
predictions + token usage to DETECTION.ROUTING_PREDICTIONS (one AI_COMPLETE call per ticket).
Run: python3 model_routing/evaluator.py
"""
import os
import random
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.snowflake_session import get_session  # noqa: E402

MODELS = ["mistral-7b", "llama3.1-8b", "llama3.1-70b", "claude-sonnet-4-5"]  # small -> large
LABELS = ["billing", "technical_issue", "account_access", "feature_request", "cancellation"]

TEMPLATES = {
    "billing": [
        "I was charged twice for my {plan} subscription this month, please refund one.",
        "My invoice for {month} shows {amount} but my plan should cost less.",
        "Why did my card get billed {amount} on the {day}? I don't recognize it.",
        "Can you send a corrected invoice with our new VAT number for {month}?",
    ],
    "technical_issue": [
        "The {feature} page keeps showing a 500 error since this morning.",
        "Exports to CSV time out after {n} minutes on the {plan} plan.",
        "The mobile app crashes whenever I open {feature}.",
        "Sync with our CRM stopped working after the update on the {day}.",
    ],
    "account_access": [
        "I can't log in, the password reset email never arrives.",
        "My two-factor device was lost, how do I regain access to my account?",
        "Our admin left the company and nobody can manage users on the {plan} workspace.",
        "I'm locked out after too many attempts, please unlock user {user}.",
    ],
    "feature_request": [
        "It would be great if {feature} supported dark mode.",
        "Please add an API endpoint to bulk-update {feature} records.",
        "Could you let us schedule reports weekly instead of only daily?",
        "We'd love SSO with Okta for the {plan} tier.",
    ],
    "cancellation": [
        "Please cancel our {plan} subscription at the end of this billing cycle.",
        "We're moving to another vendor, how do I close the account and delete data?",
        "I want to downgrade and then cancel, we no longer need {feature}.",
        "Stop auto-renewal, we will not continue after {month}.",
    ],
}
FILL = dict(plan=["Pro", "Team", "Enterprise"], month=["March", "July", "September"],
            amount=["$49", "$199", "$1,200"], day=["3rd", "14th", "28th"], n=["5", "10", "30"],
            feature=["dashboard", "reporting", "invoices", "analytics"], user=["jdoe", "asmith", "mlee"])

PROMPT = ("Classify the customer support ticket into exactly one category: "
          + ", ".join(LABELS) + ". Ticket: ")


def build_eval_set(seed=7, per_class=12) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []
    for label, temps in TEMPLATES.items():
        for i in range(per_class):
            t = temps[i % len(temps)]
            text = t.format(**{k: rng.choice(v) for k, v in FILL.items()})
            rows.append({"TICKET_ID": f"{label[:3].upper()}-{i:02d}", "TICKET_TEXT": text, "LABEL": label})
    rng.shuffle(rows)
    return pd.DataFrame(rows)


def predict_sql(model: str) -> str:
    assert model in MODELS  # model must be a string literal in AI_COMPLETE; allowlisted here
    labels = ", ".join(f"'{l}'" for l in LABELS)
    return f"""
    INSERT INTO AI_FINOPS.DETECTION.ROUTING_PREDICTIONS
    SELECT TICKET_ID, '{model}', LABEL,
           R:structured_output[0]:raw_message:category::STRING,
           R:usage:prompt_tokens::NUMBER, R:usage:completion_tokens::NUMBER, CURRENT_TIMESTAMP()
    FROM (
        SELECT TICKET_ID, LABEL,
               AI_COMPLETE(
                   model => '{model}',
                   prompt => CONCAT('{PROMPT}', TICKET_TEXT),
                   -- 100 tokens: Claude's structured output needs more headroom than 20
                   model_parameters => {{'temperature': 0, 'max_tokens': 100}},
                   response_format => {{'type': 'json', 'schema': {{'type': 'object',
                       'properties': {{'category': {{'type': 'string', 'enum': [{labels}]}}}},
                       'required': ['category'], 'additionalProperties': false}}}},
                   show_details => TRUE) AS R
        FROM AI_FINOPS.RAW.ROUTING_EVAL_SET
    )"""


def main():
    s = get_session()
    # Default: use the validated set from build_eval_set.py; --templates rebuilds the simple template set
    if "--templates" in sys.argv:
        s.write_pandas(build_eval_set(), "ROUTING_EVAL_SET", database="AI_FINOPS", schema="RAW",
                       auto_create_table=True, overwrite=True)
    s.sql("""CREATE OR REPLACE TABLE AI_FINOPS.DETECTION.ROUTING_PREDICTIONS (
                 TICKET_ID VARCHAR, MODEL_NAME VARCHAR, LABEL VARCHAR, PREDICTION VARCHAR,
                 PROMPT_TOKENS NUMBER, COMPLETION_TOKENS NUMBER, PREDICTED_AT TIMESTAMP_LTZ)""").collect()
    for m in MODELS:
        s.sql(f"ALTER SESSION SET QUERY_TAG = 'routing-eval:{m}'").collect()
        s.sql(predict_sql(m)).collect()
        print(f"scored {m}")
    s.sql("ALTER SESSION UNSET QUERY_TAG").collect()


if __name__ == "__main__":
    main()
