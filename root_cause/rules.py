"""Deterministic root-cause rules. Mirrors V_INCIDENT_CANDIDATES in sql/07_root_cause.sql (first match wins)."""
from dataclasses import dataclass
from typing import Optional

GROWTH = 1.5        # growth considered material
REQUEST_SPIKE = 2.0
RETRY_RATIO = 0.20
DUPLICATE_RATIO = 0.20
AGENT_STEPS_GROWTH = 2.0


@dataclass
class Evidence:
    req_growth: float
    in_tpr_growth: float
    out_tpr_growth: float
    retry_ratio: float
    model_changed: bool
    top_k_growth: Optional[float] = None
    duplicate_ratio: float = 0.0           # observed
    baseline_duplicate_ratio: float = 0.0
    steps_growth: float = 1.0              # agent steps per request
    unique_req_growth: Optional[float] = None    # requests excluding duplicates
    dyn_in_growth: Optional[float] = None        # non-static input tokens per step
    static_tpr_growth: Optional[float] = None    # static-prefix tokens per step

    def __post_init__(self):
        # without the finer signals, fall back to the raw growths (keeps old callers valid)
        if self.unique_req_growth is None:
            self.unique_req_growth = self.req_growth
        if self.dyn_in_growth is None:
            self.dyn_in_growth = self.in_tpr_growth / self.steps_growth


def drivers(e: Evidence) -> dict:
    return {
        "dup": e.duplicate_ratio >= DUPLICATE_RATIO and e.duplicate_ratio >= 2 * e.baseline_duplicate_ratio,
        "steps": e.steps_growth >= AGENT_STEPS_GROWTH,
        "req": e.unique_req_growth >= GROWTH,
        "model": e.model_changed,
        "static": (e.static_tpr_growth or 0) >= GROWTH,
        "in": e.dyn_in_growth >= GROWTH,
        "out": e.out_tpr_growth / e.steps_growth >= GROWTH,
    }


def classify(e: Evidence) -> str:
    d = drivers(e)
    if e.retry_ratio >= RETRY_RATIO and e.req_growth >= GROWTH:
        return "RETRY_LOOP"
    if d["dup"]:
        return "DUPLICATE_REQUESTS"
    if d["steps"]:
        return "AGENT_LOOP"
    if e.req_growth >= REQUEST_SPIKE:
        return "REQUEST_VOLUME_SPIKE"
    if d["model"]:
        return "MODEL_ROUTING_CHANGE"
    if d["static"] and e.in_tpr_growth >= GROWTH:
        return "REPEATED_CONTEXT"
    if d["in"] and (e.top_k_growth or 0) > 1:
        return "RAG_OVER_RETRIEVAL"
    if d["in"]:
        return "PROMPT_INFLATION"
    if d["out"]:
        return "OUTPUT_INFLATION"
    return "UNKNOWN"


def driver_count(e: Evidence) -> int:
    return sum(drivers(e).values())


def confidence(e: Evidence, max_abs_z: float) -> float:
    if classify(e) == "UNKNOWN":
        return 0.30
    if driver_count(e) > 1:
        return 0.60
    return 0.95 if max_abs_z >= 5 else 0.80
