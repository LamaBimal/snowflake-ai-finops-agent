import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anomaly_detection.statistical import score  # noqa: E402
from evaluation.savings_simulation import counterfactual  # noqa: E402

DAY = dict(REQUESTS=1000, INPUT_TOKENS=6_000_000, OUTPUT_TOKENS=1_000_000, CREDITS=7.0,
           RETRY_RATIO=0.0, DUPLICATE_RATIO=0.0, AVG_AGENT_STEPS=1.0, STATIC_CONTEXT_RATIO=0.1)
BASE = dict(B_IN_TPR=2000, B_STATIC=0.1, B_CPT=1e-6)


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1, abs(b))


# ------------------------------------------------------------------ scoring
def test_score_counts_and_event_recall():
    start = pd.Timestamp("2026-01-10")
    df = pd.DataFrame({
        "USAGE_DATE": [start, start + pd.Timedelta(days=1), start, start],
        "SCENARIO":   ["A", "A", None, None],
        "START_DATE": [start, start, None, None],
        "ACTUAL":     [1, 1, 0, 0],
        "FLAG":       [1, 0, 1, 0],
    })
    r = score(df, "FLAG")
    assert (r["tp"], r["fp"], r["fn"]) == (1, 1, 1)
    assert close(r["precision"], 0.5) and close(r["recall"], 0.5) and close(r["fpr"], 0.5)
    assert r["events_detected"] == "1/1" and r["mean_delay_days"] == 0


def test_score_detection_delay():
    start = pd.Timestamp("2026-01-10")
    df = pd.DataFrame({"USAGE_DATE": [start, start + pd.Timedelta(days=2)], "SCENARIO": ["A", "A"],
                       "START_DATE": [start, start], "ACTUAL": [1, 1], "FLAG": [0, 1]})
    assert score(df, "FLAG")["mean_delay_days"] == 2


# ------------------------------------------------------------------ savings
def test_prompt_inflation_trims_to_baseline():
    a = counterfactual("PROMPT_INFLATION", DAY, BASE)
    assert close(a["INPUT_TOKENS"], 1000 * 2000) and close(a["OUTPUT_TOKENS"], 1_000_000)
    assert close(a["CREDITS"], 7.0 * 3_000_000 / 7_000_000)   # same price per token


def test_rag_top_k_back_to_five():
    a = counterfactual("RAG_OVER_RETRIEVAL", DAY, BASE)
    assert close(a["INPUT_TOKENS"], 1000 * 1850)


def test_output_cap_never_increases_tokens():
    a = counterfactual("OUTPUT_INFLATION", {**DAY, "OUTPUT_TOKENS": 300_000}, BASE)
    assert close(a["OUTPUT_TOKENS"], 300_000)                  # 300/request is already under the 800 cap
    a = counterfactual("OUTPUT_INFLATION", DAY, BASE)
    assert close(a["OUTPUT_TOKENS"], 800_000)


def test_model_routing_reprices_only():
    a = counterfactual("MODEL_ROUTING_CHANGE", DAY, BASE)
    assert close(a["INPUT_TOKENS"] + a["OUTPUT_TOKENS"], 7_000_000)
    assert close(a["CREDITS"], 7.0)                           # B_CPT 1e-6 == observed price -> no change
    a = counterfactual("MODEL_ROUTING_CHANGE", DAY, {**BASE, "B_CPT": 1e-7})
    assert close(a["CREDITS"], 0.7)


def test_retry_duplicate_agent_and_static():
    assert close(counterfactual("RETRY_LOOP", {**DAY, "RETRY_RATIO": 0.8}, BASE)["CREDITS"], 7.0 * 0.2 * 1.01)
    assert close(counterfactual("DUPLICATE_REQUESTS", {**DAY, "DUPLICATE_RATIO": 0.35}, BASE)["CREDITS"], 7.0 * 0.65)
    assert close(counterfactual("AGENT_LOOP", {**DAY, "AVG_AGENT_STEPS": 16}, BASE)["CREDITS"], 7.0 * 4 / 16)
    a = counterfactual("REPEATED_CONTEXT", {**DAY, "STATIC_CONTEXT_RATIO": 0.75}, BASE)
    # static 4.5M now vs 1000*2000*0.1 = 0.2M baseline -> remove 4.3M input tokens
    assert close(a["INPUT_TOKENS"], 6_000_000 - 4_300_000)


def test_unknown_cause_is_noop():
    a = counterfactual("UNKNOWN", DAY, BASE)
    assert close(a["CREDITS"], 7.0)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all scoring + savings tests passed")
