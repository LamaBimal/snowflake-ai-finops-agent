# ADR 001: Deterministic root cause before LLM reasoning

**Status:** Accepted

## Context
LLMs given raw metrics will produce a plausible cause even when the data does not support one. For cost
incidents a wrong cause leads to the wrong fix (for example trimming prompts when the real driver is a retry loop).

## Decision
- Detection (Z-score, Isolation Forest) and root cause (ordered rules in `sql/07_root_cause.sql`) are deterministic.
- The rules store their inputs as `EVIDENCE` and a `CONFIDENCE`; no single driver gives `UNKNOWN` at 0.30.
- `AI_COMPLETE` only writes the explanation. Its prompt contains the evidence JSON and the playbook entry, says
  the cause must not be changed, and forces a fixed JSON schema (structured output).
- Saving estimates are computed in SQL from excess credits × playbook range, not by the model.

## Consequences
- Every explanation can be traced back to numbers in `INCIDENTS.EVIDENCE`.
- New anomaly types need a rule, a playbook row and a test; the model cannot "discover" new causes.
- In testing, explanations restated the evidence correctly; one minor slip (calling a 1% baseline "0%") was
  observed, which is why numeric claims in the UI come from the evidence, not the explanation text.
