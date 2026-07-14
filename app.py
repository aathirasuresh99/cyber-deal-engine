"""Streamlit demo. Two modes:
  1. Watchlist — pick a tracked company, brief is built from *stored, ingested* signals.
  2. Paste-in — the original Week 1 slice: brief from whatever you paste.
Run: streamlit run app.py"""
import streamlit as st

from src.brief import safe_generate
from src.agent import generate_brief_reflective
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


def render_agent_result(res):
    """Render a reflective AgentResult: the brief plus the self-critique trace."""
    if res.error or res.brief is None:
        st.error(f"Generation failed: {res.error}")
        return
    render_brief(res.brief)
    label = "clean on first draft" if res.revisions == 0 else f"{res.revisions} revision(s)"
    st.caption(f"Reflection agent: {label} · final verdict {'faithful' if res.faithful else 'unfaithful'}")
    with st.expander("Self-critique trace"):
        for p in res.passes:
            verdict = "✅ faithful" if p.faithful else "⚠️ unfaithful"
            st.markdown(f"**Attempt {p.attempt}** — {verdict}")
            if p.unsupported_claims:
                for c in p.unsupported_claims:
                    st.markdown(f"- {c}")
            if p.notes:
                st.caption(p.notes)


watchlist_tab, paste_tab = st.tabs(["📇 Watchlist", "📋 Paste your own"])

with watchlist_tab:
    counts = counts_by_company()
    if not counts:
        st.info(
            "No signals stored yet. This mode reads a local signal database "
            "(`python -m ingest.run_ingest` to populate it). On the public demo it's empty — "
            "use the **Paste your own** tab to try the engine on any text."
        )
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
    reflect = st.checkbox(
        "Use reflection agent (draft → self-critique → revise)",
        help="Phase 4: the agent critiques its own draft against the context and revises if it "
             "finds an unsupported claim. Costs extra calls; shows the critique trace.",
        key="p_reflect",
    )
    if st.button("Generate brief", type="primary", key="p_btn") and company_p:
        with st.spinner("Thinking..."):
            if reflect:
                render_agent_result(generate_brief_reflective(company_p, context_p))
            else:
                render_brief(safe_generate(company_p, context_p))
