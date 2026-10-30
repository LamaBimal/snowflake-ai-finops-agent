"""Benchmark Z-score vs Isolation Forest against injected anomaly labels.

Writes evaluation/benchmark.json and AI_FINOPS.DETECTION.DETECTOR_BENCHMARK.
Run: python3 evaluation/anomaly_evaluation.py
"""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anomaly_detection.statistical import load, score  # noqa: E402
from common.snowflake_session import get_session  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "benchmark.json")


def main():
    s = get_session()
    rows = []
    for detector in ("ZSCORE_7D", "ISOLATION_FOREST"):
        df = load(s, detector)
        for flag, label in (("HIGH_FLAG", "HIGH"), ("ANY_FLAG", "HIGH+WARNING")):
            r = score(df, flag)
            r.update(detector=detector, threshold=label)
            rows.append(r)

    bench = pd.DataFrame(rows)[["detector", "threshold", "tp", "fp", "fn", "precision", "recall",
                                "f1", "fpr", "events_detected", "mean_delay_days"]]
    print(bench.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    with open(OUT, "w") as f:  # close explicitly: /workspace is a stage mount
        json.dump(rows, f, indent=2, default=float)

    bench.columns = [c.upper() for c in bench.columns]
    s.write_pandas(bench, "DETECTOR_BENCHMARK", database="AI_FINOPS", schema="DETECTION",
                   auto_create_table=True, overwrite=True)
    print(f"wrote {OUT} and AI_FINOPS.DETECTION.DETECTOR_BENCHMARK")


if __name__ == "__main__":
    main()
