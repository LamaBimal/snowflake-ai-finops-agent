"""Generate synthetic Cortex AI usage (hourly grain) with injected anomaly scenarios.

Writes AI_FINOPS.RAW.SYNTHETIC_USAGE and AI_FINOPS.RAW.ANOMALY_LABELS (both replaced).
Run: python3 data/synthetic_usage.py
"""
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.snowflake_session import get_session  # noqa: E402

SCENARIO_FILE = os.path.join(os.path.dirname(__file__), "anomaly_scenarios", "scenarios.json")

# Credits per 1M tokens (illustrative, input/output blended)
MODEL_RATES = {
    "mistral-7b": 0.12,
    "llama3.1-8b": 0.19,
    "llama3.1-70b": 1.21,
    "claude-sonnet-4-5": 2.55,
}

# Baselines per application
APPS = {
    "rag-support-agent":      dict(function="AI_COMPLETE", model="llama3.1-70b",      requests=900,  input=None, output=450, rag_top_k=5),
    "sql-agent":              dict(function="AI_COMPLETE", model="claude-sonnet-4-5", requests=900,  input=1200, output=300, rag_top_k=None),
    "document-agent":         dict(function="AI_COMPLETE", model="llama3.1-70b",      requests=500,  input=1800, output=400, rag_top_k=None),
    "summarization-service":  dict(function="AI_COMPLETE", model="llama3.1-8b",       requests=2000, input=1500, output=250, rag_top_k=None),
    "classification-service": dict(function="AI_CLASSIFY", model="mistral-7b",        requests=5000, input=400,  output=10,  rag_top_k=None),
    "research-agent":         dict(function="AI_COMPLETE", model="claude-sonnet-4-5", requests=300,  input=2500, output=450, rag_top_k=None),
}
RAG_BASE_TOKENS, RAG_TOKENS_PER_CHUNK = 350, 300  # input = base + top_k * chunk
# Per-app agent steps per request and static-prefix share of input (system prompt / fixed docs)
AGENT_STEPS = {"research-agent": 3, "sql-agent": 2}
STATIC_SHARE = {"document-agent": 0.15, "rag-support-agent": 0.10, "sql-agent": 0.25}
BASE_DUPLICATE_SHARE = 0.02
HOURLY_SHAPE = np.array([1, 1, 1, 1, 1, 2, 3, 5, 7, 8, 8, 8, 7, 8, 8, 8, 7, 6, 4, 3, 2, 2, 1, 1], dtype=float)
HOURLY_SHAPE /= HOURLY_SHAPE.sum()


def active_changes(app, day_idx, scenarios):
    for s in scenarios:
        if s["application"] == app and s["start_day"] <= day_idx < s["start_day"] + s["duration"]:
            return s["change"]
    return {}


def generate(cfg):
    rng = np.random.default_rng(cfg["seed"])
    # Separate stream for columns added later, so the original columns keep identical values
    rng2 = np.random.default_rng(cfg["seed"] + 1)
    n_days = cfg["history_days"]
    start = date.today() - timedelta(days=n_days)  # last day generated = yesterday
    rows = []
    for d in range(n_days):
        day = start + timedelta(days=d)
        weekend = 0.9 if day.weekday() >= 5 else 1.0
        for app, b in APPS.items():
            ch = active_changes(app, d, cfg["scenarios"])
            model = ch.get("model", b["model"])
            top_k = ch.get("rag_top_k", b["rag_top_k"])
            requests = ch.get("requests", b["requests"]) * weekend * rng.normal(1, 0.05)
            in_base = RAG_BASE_TOKENS + top_k * RAG_TOKENS_PER_CHUNK if top_k else b["input"]
            in_base = ch.get("input_tokens", in_base)
            out_base = ch.get("output_tokens", b["output"])
            retry_share = 0.80 if "requests" in ch else 0.01

            # later-added behaviours
            dup_share = ch.get("duplicate_share", BASE_DUPLICATE_SHARE)
            dup_mult = (1 - BASE_DUPLICATE_SHARE) / (1 - dup_share)   # duplicates are extra requests
            base_steps = AGENT_STEPS.get(app, 1)
            steps = ch.get("agent_steps", base_steps)
            step_mult = steps / base_steps                           # every step re-sends and re-generates
            # static prefix is sized from the app's *baseline* input, so prompt/RAG inflation stays dynamic
            base_in = RAG_BASE_TOKENS + b["rag_top_k"] * RAG_TOKENS_PER_CHUNK if b["rag_top_k"] else b["input"]
            static_tokens = base_in * STATIC_SHARE.get(app, 0.05)
            extra_static = ch.get("static_prefix_tokens", 0)
            for h in range(24):
                req = max(1, int(round(requests * HOURLY_SHAPE[h] * rng.normal(1, 0.08))))
                in_noise, out_noise = rng.normal(1, 0.06), rng.normal(1, 0.06)
                req = max(1, int(round(req * dup_mult)))
                in_per_req = (in_base * step_mult + extra_static) * in_noise
                in_tok = int(req * in_per_req)
                out_tok = int(req * out_base * step_mult * out_noise)
                cacheable = int(req * (static_tokens * step_mult + extra_static) * rng2.normal(1, 0.03))
                rows.append({
                    "USAGE_TIME": datetime(day.year, day.month, day.day, h, tzinfo=timezone.utc),
                    "QUERY_ID": str(uuid.UUID(int=int(rng.integers(0, 2**63)) << 64 | d << 16 | h)),
                    "APPLICATION": app,
                    "USER_ID": f"svc_{app.replace('-', '_')}",
                    "ROLE_NAME": "AI_APP_ROLE",
                    "FUNCTION_NAME": b["function"],
                    "MODEL_NAME": model,
                    "INPUT_TOKENS": in_tok,
                    "OUTPUT_TOKENS": out_tok,
                    "CREDITS": round((in_tok + out_tok) / 1e6 * MODEL_RATES[model], 6),
                    "REQUEST_COUNT": req,
                    "RETRY_COUNT": int(req * retry_share),
                    "RAG_TOP_K": top_k,
                    "DUPLICATE_COUNT": int(req * dup_share * rng2.normal(1, 0.05)),
                    "AGENT_STEPS": int(round(req * steps)),
                    "CACHEABLE_INPUT_TOKENS": min(cacheable, in_tok),
                })
    labels = [{
        "SCENARIO": s["scenario"],
        "APPLICATION": s["application"],
        "START_DATE": start + timedelta(days=s["start_day"]),
        "END_DATE": start + timedelta(days=s["start_day"] + s["duration"] - 1),
        "EXPECTED_CAUSE": s["expected_cause"],
    } for s in cfg["scenarios"]]
    return pd.DataFrame(rows), pd.DataFrame(labels)


def main():
    cfg = json.load(open(SCENARIO_FILE))
    usage, labels = generate(cfg)
    session = get_session()
    session.sql("TRUNCATE TABLE AI_FINOPS.RAW.SYNTHETIC_USAGE").collect()
    session.sql("TRUNCATE TABLE AI_FINOPS.RAW.ANOMALY_LABELS").collect()
    session.write_pandas(usage, "SYNTHETIC_USAGE", schema="RAW", database="AI_FINOPS", use_logical_type=True)
    session.write_pandas(labels, "ANOMALY_LABELS", schema="RAW", database="AI_FINOPS")
    print(f"wrote {len(usage)} usage rows, {len(labels)} labels")


if __name__ == "__main__":
    main()
