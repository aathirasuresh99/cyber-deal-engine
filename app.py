"""Streamlit demo. Two modes:
  1. Watchlist — pick a tracked company, brief is built from *stored, ingested* signals.
  2. Paste-in — the original Week 1 slice: brief from whatever you paste.
Run: streamlit run app.py"""
import streamlit as st

from src.brief import safe_generate
from src.store import counts_by_company
from src import retrieve

st.set_page_config(page_title="Cyber Deal Engine", page_icon="🛡️")
st.title("🛡️ Cyber Deal Engine")
st.caption("Turning cybersecurity signals into pre-meeting sales briefs.")


def render_brief(result):
    """Shared renderer for a Brief object or an error dict."""
    if hasattr(result, "model_dump"):
        b = result
        if not b.has_signal:
            st.warning("No strong signal detected — showing discovery angles, no fabricated incidents.")
        st.subheader("Key points")
        for kp in b.key_points:
            st.markdown(f"- {kp}")
        st.subheader("Opener")
        st.info(b.opener)
        st.subheader("Objection questions")
        for q in b.objection_questions:
            st.markdown(f"- {q}")
        with st.expander("Raw JSON"):
            st.json(b.model_dump())
    else:
        st.error(f"Generation failed: {result.get('error')}")


watchlist_tab, paste_tab = st.tabs(["📇 Watchlist", "📋 Paste your own"])

with watchlist_tab:
    counts = counts_by_company()
    if not counts:
        st.info("No signals stored yet. Run `python -m ingest.run_ingest` first.")
    else:
        # Show each company with how many signals we hold.
        options = sorted(counts.keys())
        company = st.selectbox(
            "Tracked company",
            options,
            format_func=lambda c: f"{c}  ({counts[c]} signals)",
        )
        rep = retrieve.retrieval_report(company)
        st.caption(
            f"{rep['relevant']} relevant of {rep['raw']} stored "
            f"({rep['dropped_nvd_noise']} filtered as NVD name-collision noise)."
        )
        context = retrieve.build_context(company)
        with st.expander("Signals feeding this brief"):
            st.text(context or "(nothing relevant after filtering)")

        if st.button("Generate brief", type="primary", key="wl_btn"):
            with st.spinner("Thinking..."):
                render_brief(safe_generate(company, context))

with paste_tab:
    company_p = st.text_input("Prospect company", placeholder="e.g. Razorpay", key="p_company")
    context_p = st.text_area(
        "What you know (paste anything: news, breach reports, CVEs, notes)",
        height=180,
        placeholder="Paste raw signals here.",
        key="p_context",
    )
    if st.button("Generate brief", type="primary", key="p_btn") and company_p:
        with st.spinner("Thinking..."):
            render_brief(safe_generate(company_p, context_p))
