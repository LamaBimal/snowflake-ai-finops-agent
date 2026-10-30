import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from root_cause.rules import Evidence, classify, confidence  # noqa: E402

BASE = dict(req_growth=1.0, in_tpr_growth=1.0, out_tpr_growth=1.0, retry_ratio=0.01, model_changed=False)


def ev(**kw):
    return Evidence(**{**BASE, **kw})


def test_retry_loop_beats_request_spike():
    assert classify(ev(req_growth=5.0, retry_ratio=0.8)) == "RETRY_LOOP"


def test_request_spike():
    assert classify(ev(req_growth=2.5)) == "REQUEST_VOLUME_SPIKE"


def test_model_routing():
    assert classify(ev(model_changed=True)) == "MODEL_ROUTING_CHANGE"


def test_rag_vs_prompt_inflation():
    assert classify(ev(in_tpr_growth=4.0, top_k_growth=5.0)) == "RAG_OVER_RETRIEVAL"
    assert classify(ev(in_tpr_growth=3.6)) == "PROMPT_INFLATION"


def test_output_inflation():
    assert classify(ev(out_tpr_growth=4.2)) == "OUTPUT_INFLATION"


def test_unknown_low_confidence():
    assert classify(ev()) == "UNKNOWN"
    assert confidence(ev(), max_abs_z=3.6) == 0.30


def test_mixed_drivers_lower_confidence():
    assert confidence(ev(in_tpr_growth=2.0, out_tpr_growth=2.0), max_abs_z=10) == 0.60


def test_duplicate_requests_not_retry_or_spike():
    e = ev(req_growth=1.5, duplicate_ratio=0.35, baseline_duplicate_ratio=0.02, unique_req_growth=1.0)
    assert classify(e) == "DUPLICATE_REQUESTS"
    assert confidence(e, max_abs_z=10) == 0.95   # unique traffic flat -> single driver


def test_agent_loop_explains_token_growth():
    e = ev(in_tpr_growth=5.0, out_tpr_growth=5.0, steps_growth=5.0)
    assert classify(e) == "AGENT_LOOP"
    assert confidence(e, max_abs_z=10) == 0.95   # token growth is per-step flat -> single driver


def test_repeated_context_vs_prompt_inflation():
    rc = ev(in_tpr_growth=3.2, dyn_in_growth=1.0, static_tpr_growth=15.0)
    assert classify(rc) == "REPEATED_CONTEXT"
    pi = ev(in_tpr_growth=3.6, dyn_in_growth=3.6, static_tpr_growth=1.0)
    assert classify(pi) == "PROMPT_INFLATION"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all root-cause rule tests passed")
