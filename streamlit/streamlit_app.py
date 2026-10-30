Can we"""AI FinOps dashboard: spend, anomalies, root cause, recommendations, detector benchmark, model routing."""
import html
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="AI FinOps", layout="wide")
st.title("AI FinOps Monitor")
st.caption("Cortex AI usage, anomaly detection, root cause, and optimization (AI_FINOPS database)")

conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))
session = conn.session()


@st.cache_data(ttl=600, show_spinner=False)
def run(sql: str, params: tuple = ()) -> pd.DataFrame:
    return session.sql(sql, params=list(params)).to_pandas()


def safe(sql: str, params: tuple = ()) -> pd.DataFrame | None:
    """Return None when an optional table (e.g. later-phase output) is missing."""
    try:
        return run(sql, params)
    except Exception:
        return None


def kpi(where, label, value, delta=None, delta_color="normal"):
    """KPI card with the same arguments as st.metric, rendered with core st.markdown.

    st.metric's lazily loaded frontend module (Metric.js) failed to load in Snowsight for this
    Streamlit version, so cards are drawn as plain HTML instead. Inputs are escaped.
    """
    d = ""
    if delta:
        up = str(delta).strip().startswith("+")
        good = up if delta_color == "normal" else not up
        color = "#1e7a46" if good else "#a8233a"
        d = (f'<div style="color:{color};font-size:13px;margin-top:2px">'
             f'{"▲" if up else "▼"} {html.escape(str(delta))}</div>')
    where.markdown(
        f'<div style="border:1px solid #e1e7ef;border-radius:8px;padding:10px 14px;margin-bottom:8px">'
        f'<div style="color:#5b6778;font-size:13px">{html.escape(str(label))}</div>'
        f'<div style="font-size:26px;font-weight:600;line-height:1.2">{html.escape(str(value))}</div>{d}</div>',
        unsafe_allow_html=True)


def clear_cache():
    run.clear()


with st.sidebar:
    source = st.segmented_control("Data source", ["SYNTHETIC", "REAL"], default="SYNTHETIC")
    days = st.slider("Lookback (days)", 7, 90, 60)
    st.button("Refresh data", on_click=clear_cache, icon=":material/refresh:")

source = source or "SYNTHETIC"
P = (source, days)

tab_how, tab_spend, tab_anom, tab_rc, tab_sim, tab_bench, tab_route = st.tabs(
    ["How it works", "Spend overview", "Anomaly center", "Root cause & recommendations", "Savings simulation",
     "Detector benchmark", "Model routing"])

# ---------------------------------------------------------------- how it works
with tab_how:
    # Static process diagram (copy of docs/process_diagram.html, listed in snowflake.yml artifacts)
    diagram = Path(__file__).parent / "process_diagram.html"
    if diagram.exists():
        html_doc = diagram.read_text(encoding="utf-8")
        if hasattr(st, "iframe"):
            st.iframe(html_doc, height=2600)
        else:  # older Streamlit without st.iframe
            import streamlit.components.v1 as components
            components.html(html_doc, height=2600, scrolling=True)
    else:
        st.warning("process_diagram.html not found next to the app; add it to snowflake.yml artifacts.")

# ---------------------------------------------------------------- spend
with tab_spend:
    with st.spinner("Loading spend..."):
        daily = run("""
            SELECT USAGE_DATE, APPLICATION, CREDITS, TOTAL_TOKENS, REQUESTS
            FROM AI_FINOPS.ANALYTICS.DAILY_METRICS
            WHERE SOURCE = ? AND USAGE_DATE >= DATEADD('DAY', -?, CURRENT_DATE())
            ORDER BY USAGE_DATE""", P)
    if daily.empty:
        st.info("No usage for this source and window.")
    else:
        last = daily.USAGE_DATE.max()
        cur = daily[daily.USAGE_DATE == last]
        prior = daily[(daily.USAGE_DATE < last) & (daily.USAGE_DATE >= last - pd.Timedelta(days=7))]
        prior_cr = prior.CREDITS.sum() / max(prior.USAGE_DATE.nunique(), 1)
        c1, c2, c3, c4 = st.columns(4)
        kpi(c1, "Credits (latest day)", f"{cur.CREDITS.sum():,.2f}",
                  f"{(cur.CREDITS.sum() / prior_cr - 1) * 100:+.0f}% vs 7d avg" if prior_cr else None,
                  delta_color="inverse")
        kpi(c2, "Tokens (latest day)", f"{cur.TOTAL_TOKENS.sum() / 1e6:,.1f}M")
        kpi(c3, "Requests (latest day)", f"{int(cur.REQUESTS.sum()):,}")
        kpi(c4, f"Credits ({days}d)", f"{daily.CREDITS.sum():,.1f}")

        st.subheader("Daily credits by application")
        st.area_chart(daily.pivot_table(index="USAGE_DATE", columns="APPLICATION", values="CREDITS", aggfunc="sum"))
        st.subheader("Credits by application")
        st.bar_chart(daily.groupby("APPLICATION").CREDITS.sum().sort_values(ascending=False), horizontal=True)

# ---------------------------------------------------------------- anomalies
with tab_anom:
    anomalies = run("""
        SELECT USAGE_DATE, APPLICATION, METRIC, SEVERITY, DETECTOR,
               ROUND(EXPECTED_VALUE, 2) AS EXPECTED, ROUND(OBSERVED_VALUE, 2) AS OBSERVED,
               ROUND(PCT_CHANGE * 100, 1) AS PCT_CHANGE, ROUND(Z_SCORE, 1) AS Z_SCORE
        FROM AI_FINOPS.DETECTION.ANOMALIES
        WHERE SOURCE = ? AND USAGE_DATE >= DATEADD('DAY', -?, CURRENT_DATE())
        ORDER BY USAGE_DATE DESC, ABS(Z_SCORE) DESC NULLS LAST""", P)
    detectors = sorted(anomalies.DETECTOR.unique()) if not anomalies.empty else []
    det = st.pills("Detector", detectors, default=detectors[0] if detectors else None)
    sev = st.pills("Severity", ["HIGH", "WARNING"], selection_mode="multi", default=["HIGH"])
    view = anomalies[(anomalies.DETECTOR == det) & (anomalies.SEVERITY.isin(sev or ["HIGH", "WARNING"]))]
    kpi(st, "Anomaly rows", len(view))
    st.dataframe(view, hide_index=True, use_container_width=True,
                 column_config={"PCT_CHANGE": st.column_config.NumberColumn("% change", format="%+.1f%%")})

# ---------------------------------------------------------------- root cause
with tab_rc:
    inc = run("""
        SELECT * FROM AI_FINOPS.DETECTION.V_INCIDENT_REPORT
        WHERE SOURCE = ? AND START_DATE >= DATEADD('DAY', -?, CURRENT_DATE())
        ORDER BY START_DATE DESC""", P)
    if inc.empty:
        st.info("No incidents in this window.")
    else:
        c1, c2, c3 = st.columns(3)
        kpi(c1, "Incidents", len(inc))
        kpi(c2, "Excess credits", f"{inc.EXCESS_CREDITS.sum():,.2f}")
        lo, hi = inc.EST_SAVING_CREDITS_LOW.sum(), inc.EST_SAVING_CREDITS_HIGH.sum()
        kpi(c3, "Estimated avoidable credits", f"{lo:,.1f} – {hi:,.1f}")

        for _, r in inc.iterrows():
            icon = ":material/error:" if r.MAX_SEVERITY == "HIGH" else ":material/warning:"
            title = f"{r.APPLICATION} · {r.ROOT_CAUSE} · {r.START_DATE} → {r.END_DATE}"
            with st.expander(title, icon=icon, expanded=False):
                m1, m2, m3, m4 = st.columns(4)
                kpi(m1, "Baseline credits/day", f"{r.BASELINE_CREDITS:,.2f}")
                kpi(m2, "Observed credits/day", f"{r.OBSERVED_CREDITS:,.2f}",
                          f"{(r.OBSERVED_CREDITS / r.BASELINE_CREDITS - 1) * 100:+.0f}%" if r.BASELINE_CREDITS else None,
                          delta_color="inverse")
                kpi(m3, "Rule confidence", f"{r.CONFIDENCE:.0%}")
                kpi(m4, "Quality risk", r.QUALITY_RISK or "—")
                if r.AI_PROBLEM:
                    st.markdown(f"**Problem:** {r.AI_PROBLEM}")
                    ev = json.loads(r.AI_EVIDENCE) if isinstance(r.AI_EVIDENCE, str) else (r.AI_EVIDENCE or [])
                    st.markdown("**Evidence**\n" + "\n".join(f"- {e}" for e in ev))
                    st.success(f"**Recommendation:** {r.AI_RECOMMENDATION}")
                    st.caption(f"Playbook saving range: {r.AI_ESTIMATED_SAVING} · "
                               f"≈ {r.EST_SAVING_CREDITS_LOW:,.2f}–{r.EST_SAVING_CREDITS_HIGH:,.2f} credits over this incident")
                else:
                    st.info("No Cortex explanation yet. Run CALL AI_FINOPS.DETECTION.SP_EXPLAIN_INCIDENTS(FALSE).")
                with st.popover("Raw evidence (deterministic)"):
                    st.json(json.loads(r.EVIDENCE) if isinstance(r.EVIDENCE, str) else r.EVIDENCE)

# ---------------------------------------------------------------- benchmark
with tab_bench:
    bench = safe("SELECT * FROM AI_FINOPS.DETECTION.DETECTOR_BENCHMARK ORDER BY DETECTOR, THRESHOLD")
    if bench is None or bench.empty:
        st.info("Benchmark not available yet. Run anomaly_detection/anomaly_evaluation.py (evaluation/).")
    else:
        st.dataframe(bench, hide_index=True, use_container_width=True)
        st.bar_chart(bench, x="DETECTOR", y=["PRECISION", "RECALL", "F1"], stack=False)

# ---------------------------------------------------------------- routing
with tab_route:
    routing = safe("SELECT * FROM AI_FINOPS.DETECTION.MODEL_ROUTING_RESULTS ORDER BY CREDITS_PER_1K_REQUESTS")
    if routing is None or routing.empty:
        st.info("Model-routing experiment not run yet. Run model_routing/evaluator.py.")
    else:
        rec = routing[routing.RECOMMENDED]
        if not rec.empty:
            r = rec.iloc[0]
            st.success(f"Recommended model: **{r.MODEL_NAME}** · accuracy {r.ACCURACY:.1%} · "
                       f"saving vs most expensive {r.SAVING_VS_LARGEST:.0%}")
        st.dataframe(routing, hide_index=True, use_container_width=True,
                     column_config={"ACCURACY": st.column_config.ProgressColumn("Accuracy", min_value=0, max_value=1, format="percent"),
                                    "SAVING_VS_LARGEST": st.column_config.NumberColumn("Saving vs largest", format="percent")})
        st.scatter_chart(routing, x="CREDITS_PER_1K_REQUESTS", y="ACCURACY", color="MODEL_NAME")

# ---------------------------------------------------------------- savings simulation
with tab_sim:
    sim = safe("SELECT * FROM AI_FINOPS.DETECTION.SAVINGS_SIMULATION ORDER BY CREDITS_BEFORE - CREDITS_AFTER DESC")
    if sim is None or sim.empty:
        st.info("Savings simulation not run yet. Run evaluation/savings_simulation.py.")
    else:
        st.caption("Synthetic data. Each playbook fix is applied as a concrete counterfactual to the incident days.")
        before, after = sim.CREDITS_BEFORE.sum(), sim.CREDITS_AFTER.sum()
        c1, c2, c3 = st.columns(3)
        kpi(c1, "Incident credits before", f"{before:,.1f}")
        kpi(c2, "After fixes", f"{after:,.1f}", f"{(after / before - 1) * 100:+.0f}%", delta_color="inverse")
        kpi(c3, "Avoidable credits", f"{before - after:,.1f}")
        st.bar_chart(sim.set_index("ROOT_CAUSE")[["CREDITS_BEFORE", "CREDITS_AFTER"]], stack=False)
        st.dataframe(sim[["APPLICATION", "ROOT_CAUSE", "DAYS", "CREDITS_BEFORE", "CREDITS_AFTER", "SAVING_PCT",
                          "TOKEN_REDUCTION_PCT", "QUALITY_BEFORE", "QUALITY_AFTER", "QUALITY_BASIS"]],
                     hide_index=True, use_container_width=True,
                     column_config={"SAVING_PCT": st.column_config.NumberColumn("Saving", format="percent"),
                                    "TOKEN_REDUCTION_PCT": st.column_config.NumberColumn("Token reduction", format="percent"),
                                    "QUALITY_BEFORE": st.column_config.NumberColumn("Quality before", format="percent"),
                                    "QUALITY_AFTER": st.column_config.NumberColumn("Quality after", format="percent")})
