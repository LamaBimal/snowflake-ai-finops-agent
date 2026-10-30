"""Before/after savings simulation.

For every synthetic incident with a known root cause, apply the playbook fix as a concrete
counterfactual to the incident days and re-price the tokens:

  RAG_OVER_RETRIEVAL    top_k back to 5           -> input/request = 350 + 5*300
  PROMPT_INFLATION      trim history to baseline  -> input/request = baseline
  OUTPUT_INFLATION      max_tokens = 800          -> output/request = min(observed, 800)
  MODEL_ROUTING_CHANGE  route back                -> baseline model's credits/token
  RETRY_LOOP            capped retries (1%)       -> requests = unique * 1.01
  DUPLICATE_REQUESTS    response cache            -> duplicate requests cost nothing
  AGENT_LOOP            max 4 agent steps         -> tokens * min(steps, 4) / steps
  REPEATED_CONTEXT      reuse static prefix       -> static tokens back to baseline share

Quality: only MODEL_ROUTING_CHANGE changes the model, so quality before/after uses the measured
routing accuracy (DETECTION.MODEL_ROUTING_RESULTS). Other fixes are assumed quality-neutral; that
is an assumption, not a measurement, and is labelled as such in the output.

Writes DETECTION.SAVINGS_SIMULATION and evaluation/savings_simulation.json.
Run: python3 evaluation/savings_simulation.py
"""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

OUT = os.path.join(os.path.dirname(__file__), "savings_simulation.json")
RAG_TOKENS_FIXED = 350 + 5 * 300
MAX_OUTPUT_TOKENS = 800
MAX_AGENT_STEPS = 4
RETRY_CAP = 0.01


def counterfactual(cause: str, day: dict, base: dict) -> dict:
    """Return (input_tokens, output_tokens, credits) for one incident day after the fix.

    day:  REQUESTS, INPUT_TOKENS, OUTPUT_TOKENS, CREDITS, RETRY_RATIO, DUPLICATE_RATIO,
          AVG_AGENT_STEPS, STATIC_CONTEXT_RATIO
    base: B_IN_TPR, B_STATIC, B_CPT (baseline credits per token)
    """
    req, inp, out, cr = day["REQUESTS"], day["INPUT_TOKENS"], day["OUTPUT_TOKENS"], day["CREDITS"]
    cpt = cr / max(inp + out, 1)             # same-model price for this day
    in_tpr, out_tpr = inp / req, out / req

    if cause == "RAG_OVER_RETRIEVAL":
        inp = req * min(in_tpr, RAG_TOKENS_FIXED)
    elif cause == "PROMPT_INFLATION":
        inp = req * min(in_tpr, base["B_IN_TPR"])
    elif cause == "OUTPUT_INFLATION":
        out = req * min(out_tpr, MAX_OUTPUT_TOKENS)
    elif cause == "MODEL_ROUTING_CHANGE":
        cpt = min(cpt, base["B_CPT"])
    elif cause == "RETRY_LOOP":
        unique = req * (1 - day["RETRY_RATIO"])
        new_req = unique * (1 + RETRY_CAP)
        inp, out = in_tpr * new_req, out_tpr * new_req
    elif cause == "DUPLICATE_REQUESTS":
        keep = 1 - (day["DUPLICATE_RATIO"] or 0)
        inp, out = inp * keep, out * keep
    elif cause == "AGENT_LOOP":
        steps = day["AVG_AGENT_STEPS"] or 1
        f = min(steps, MAX_AGENT_STEPS) / steps
        inp, out = inp * f, out * f
    elif cause == "REPEATED_CONTEXT":
        static_now = inp * (day["STATIC_CONTEXT_RATIO"] or 0)
        static_base = req * base["B_IN_TPR"] * (base["B_STATIC"] or 0)
        inp = inp - max(static_now - static_base, 0)
    return {"INPUT_TOKENS": inp, "OUTPUT_TOKENS": out, "CREDITS": (inp + out) * cpt}


DAYS_SQL = """
WITH I AS (
    SELECT INCIDENT_ID, APPLICATION, START_DATE, END_DATE, ROOT_CAUSE,
           EVIDENCE:model:baseline::STRING AS B_MODEL, EVIDENCE:model:observed::STRING AS O_MODEL
    FROM AI_FINOPS.DETECTION.INCIDENTS
    WHERE SOURCE = 'SYNTHETIC' AND ROOT_CAUSE <> 'UNKNOWN'
),
B AS (   -- 7-day pre-incident baseline
    SELECT I.INCIDENT_ID,
           SUM(D.INPUT_TOKENS) / NULLIF(SUM(D.REQUESTS), 0)                     AS B_IN_TPR,
           SUM(D.STATIC_CONTEXT_RATIO * D.INPUT_TOKENS) / NULLIF(SUM(D.INPUT_TOKENS), 0) AS B_STATIC,
           SUM(D.CREDITS) / NULLIF(SUM(D.TOTAL_TOKENS), 0)                      AS B_CPT
    FROM I JOIN AI_FINOPS.ANALYTICS.DAILY_METRICS D
      ON D.SOURCE = 'SYNTHETIC' AND D.APPLICATION = I.APPLICATION
     AND D.USAGE_DATE BETWEEN DATEADD('DAY', -7, I.START_DATE) AND DATEADD('DAY', -1, I.START_DATE)
    GROUP BY 1
)
SELECT I.*, B.B_IN_TPR, B.B_STATIC, B.B_CPT, D.USAGE_DATE, D.REQUESTS, D.INPUT_TOKENS, D.OUTPUT_TOKENS,
       D.CREDITS, D.RETRY_RATIO, D.DUPLICATE_RATIO, D.AVG_AGENT_STEPS, D.STATIC_CONTEXT_RATIO
FROM I JOIN B USING (INCIDENT_ID)
JOIN AI_FINOPS.ANALYTICS.DAILY_METRICS D
  ON D.SOURCE = 'SYNTHETIC' AND D.APPLICATION = I.APPLICATION
 AND D.USAGE_DATE BETWEEN I.START_DATE AND I.END_DATE
"""


def simulate(days: pd.DataFrame, routing: pd.DataFrame) -> pd.DataFrame:
    acc = dict(zip(routing.MODEL_NAME, routing.ACCURACY)) if not routing.empty else {}
    rows = []
    for inc_id, g in days.groupby("INCIDENT_ID"):
        first = g.iloc[0]
        base = {"B_IN_TPR": first.B_IN_TPR, "B_STATIC": first.B_STATIC, "B_CPT": first.B_CPT}
        after = [counterfactual(first.ROOT_CAUSE, r._asdict(), base) for r in g.itertuples(index=False)]
        tok_before = float((g.INPUT_TOKENS + g.OUTPUT_TOKENS).sum())
        tok_after = sum(a["INPUT_TOKENS"] + a["OUTPUT_TOKENS"] for a in after)
        cr_before, cr_after = float(g.CREDITS.sum()), sum(a["CREDITS"] for a in after)
        if first.ROOT_CAUSE == "MODEL_ROUTING_CHANGE" and first.O_MODEL in acc and first.B_MODEL in acc:
            q_before, q_after, q_basis = acc[first.O_MODEL], acc[first.B_MODEL], "MEASURED (routing eval)"
        else:
            q_before = q_after = None
            q_basis = "ASSUMED UNCHANGED (fix does not change the model)"
        rows.append({
            "INCIDENT_ID": inc_id, "APPLICATION": first.APPLICATION, "ROOT_CAUSE": first.ROOT_CAUSE,
            "START_DATE": str(first.START_DATE), "END_DATE": str(first.END_DATE), "DAYS": len(g),
            "CREDITS_BEFORE": cr_before, "CREDITS_AFTER": cr_after,
            "SAVING_PCT": 1 - cr_after / cr_before if cr_before else 0.0,
            "TOKENS_BEFORE": tok_before, "TOKENS_AFTER": tok_after,
            "TOKEN_REDUCTION_PCT": 1 - tok_after / tok_before if tok_before else 0.0,
            "QUALITY_BEFORE": q_before, "QUALITY_AFTER": q_after, "QUALITY_BASIS": q_basis,
        })
    return pd.DataFrame(rows)


def main():
    from common.snowflake_session import get_session
    s = get_session()
    days = s.sql(DAYS_SQL).to_pandas()
    try:
        routing = s.sql("SELECT MODEL_NAME, ACCURACY FROM AI_FINOPS.DETECTION.MODEL_ROUTING_RESULTS").to_pandas()
    except Exception:
        routing = pd.DataFrame(columns=["MODEL_NAME", "ACCURACY"])
    res = simulate(days, routing)

    # 30-day window: non-incident days are unchanged, so after = total - incident savings
    total_30d = s.sql("""SELECT SUM(CREDITS) FROM AI_FINOPS.ANALYTICS.DAILY_METRICS
                         WHERE SOURCE = 'SYNTHETIC'
                           AND USAGE_DATE > DATEADD('DAY', -30, (SELECT MAX(USAGE_DATE) FROM AI_FINOPS.ANALYTICS.DAILY_METRICS
                                                                 WHERE SOURCE = 'SYNTHETIC'))""").collect()[0][0]
    last = pd.to_datetime(days.USAGE_DATE).max()
    in30 = res[pd.to_datetime(res.START_DATE) > last - pd.Timedelta(days=30)]
    saved_30d = float((in30.CREDITS_BEFORE - in30.CREDITS_AFTER).sum())
    summary = {
        "window_days": 30,
        "credits_before": float(total_30d),
        "credits_after": float(total_30d) - saved_30d,
        "cost_reduction_pct": saved_30d / float(total_30d),
        "incidents_in_window": int(len(in30)),
        "incident_credits_before": float(res.CREDITS_BEFORE.sum()),
        "incident_credits_after": float(res.CREDITS_AFTER.sum()),
    }

    pd.set_option("display.width", 200)
    print(res[["APPLICATION", "ROOT_CAUSE", "DAYS", "CREDITS_BEFORE", "CREDITS_AFTER", "SAVING_PCT",
               "TOKEN_REDUCTION_PCT", "QUALITY_BEFORE", "QUALITY_AFTER"]].round(3).to_string(index=False))
    print(json.dumps(summary, indent=2))

    with open(OUT, "w") as f:  # close explicitly: /workspace is a stage mount
        json.dump({"summary": summary, "incidents": res.to_dict(orient="records")}, f, indent=2, default=float)
    s.write_pandas(res, "SAVINGS_SIMULATION", database="AI_FINOPS", schema="DETECTION",
                   auto_create_table=True, overwrite=True)
    print(f"wrote {OUT} and AI_FINOPS.DETECTION.SAVINGS_SIMULATION")


if __name__ == "__main__":
    main()
