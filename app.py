"""Streamlit demo — Cyber Deal Engine.

Three ways in, one engine:
  1. Live brief (default) — type any company; fetch real signals LIVE (NVD + news) and brief it
     on the spot. This is the real-time path: no pre-ingestion, works on any prospect.
  2. Watchlist — pick a tracked company; brief from *stored* signals (needs a local signal DB).
  3. Paste your own — brief from arbitrary pasted text (news, CVEs, notes).

Run: streamlit run app.py
"""
import csv
from pathlib import Path

import streamlit as st

from src.brief import safe_generate
from src.agent import generate_brief_reflective
from src.store import counts_by_company
from src.schema import Trigger, TRIGGER_LABELS, TRIGGER_PRIORITY
from src import retrieve, live
from src.config import ACTIVE_MARKET

st.set_page_config(page_title="Cyber Deal Engine", page_icon="🛡️", layout="wide")

# ---- light styling: trigger pills + signal cards ---------------------------------
st.markdown(
    """
    <style>
      .pill {display:inline-block;padding:3px 10px;margin:2px 4px 2px 0;border-radius:12px;
             font-size:0.78rem;font-weight:600;color:#fff;}
      .pill-red{background:#c0392b;} .pill-orange{background:#d68910;}
      .pill-blue{background:#2471a3;} .pill-gray{background:#5d6d7e;}
      .sig-card{border:1px solid #e1e4e8;border-left:4px solid #2471a3;border-radius:6px;
                padding:10px 14px;margin:6px 0;background:rgba(127,127,127,0.04);}
      .sig-src{font-size:0.72rem;font-weight:700;text-transform:uppercase;color:#2471a3;letter-spacing:.04em;}
      .sig-date{font-size:0.72rem;color:#8a8f98;float:right;}
      .sig-title{font-weight:600;margin:2px 0;}
      .sig-body{font-size:0.85rem;color:#6b7280;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🛡️ Cyber Deal Engine")
st.caption(
    f"Real security signals → grounded pre-meeting sales briefs. "
    f"Never fabricates a breach, CVE, date, or number. Market: {ACTIVE_MARKET.label}."
)

# Urgency → colour, so the hero trigger reads first at a glance.
_PILL_COLOR = {
    Trigger.BREACH: "pill-red", Trigger.VULNERABILITY: "pill-red",
    Trigger.COMPLIANCE: "pill-orange", Trigger.PEER_BREACH: "pill-orange",
    Trigger.MA_FUNDING: "pill-blue", Trigger.GROWTH: "pill-blue",
    Trigger.DEAL_DEMAND: "pill-gray", Trigger.INSURER_BOARD: "pill-gray",
    Trigger.VISIBILITY: "pill-gray",
}


def _quick_picks() -> list[str]:
    """Watchlist company names from data/target_companies.csv, for one-click live briefs."""
    path = Path(__file__).parent / "data" / "target_companies.csv"
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as f:
            return [row["company_name"].strip() for row in csv.DictReader(f) if row.get("company_name")]
    except Exception:  # noqa: BLE001
        return []


def render_triggers(brief):
    """Colored pills for the detected buying triggers, most-urgent-first."""
    if not brief.triggers:
        return
    ordered = [t for t in TRIGGER_PRIORITY if t in brief.triggers]
    pills = "".join(
        f'<span class="pill {_PILL_COLOR.get(t, "pill-gray")}">{TRIGGER_LABELS.get(t, t.value)}</span>'
        for t in ordered
    )
    st.markdown(f"**Buying triggers detected:**<br>{pills}", unsafe_allow_html=True)


def render_signal_cards(signals):
    """Render live/stored signals as source-tagged cards with links."""
    for s in signals:
        when = s.published.date().isoformat() if s.published else "date unknown"
        body = (s.body or "")[:240]
        title = s.title
        link = f'<a href="{s.url}" target="_blank">{title}</a>' if getattr(s, "url", "") else title
        st.markdown(
            f'<div class="sig-card"><span class="sig-src">{s.source}</span>'
            f'<span class="sig-date">{when}</span>'
            f'<div class="sig-title">{link}</div>'
            f'<div class="sig-body">{body}</div></div>',
            unsafe_allow_html=True,
        )


def render_brief(result):
    """Shared renderer for a Brief object or an error dict."""
    if hasattr(result, "model_dump"):
        b = result
        if not b.has_signal:
            st.warning(
                "No actionable buying trigger found in the signals — showing generic discovery "
                "angles. Nothing here is invented."
            )
        else:
            render_triggers(b)
        st.markdown(f"**Why now:** {b.why_now}")
        st.subheader("Key points")
        for kp in b.key_points:
            st.markdown(f"- {kp}")
        st.subheader("Opener")
        st.info(b.opener)
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Who to engage")
            st.caption("Likely roles — confirm the real contacts.")
            for s in b.stakeholders:
                st.markdown(f"- {s}")
        with col_b:
            st.subheader("Discovery — what to ask")
            st.caption("To uncover stack, pain cost, and budget/timing.")
            for q in b.discovery_questions:
                st.markdown(f"- {q}")
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


live_tab, watchlist_tab, paste_tab = st.tabs(
    ["🔍 Live brief", "📇 Watchlist", "📋 Paste your own"]
)

# ---- 1. LIVE BRIEF (default, search-first) ---------------------------------------
with live_tab:
    st.markdown("**Brief me on any company — right now.** Fetches real signals live, then briefs.")

    if "live_company" not in st.session_state:
        st.session_state.live_company = ""

    picks = _quick_picks()
    if picks:
        st.caption("Quick picks (watchlist):")
        cols = st.columns(min(6, len(picks)))
        for i, name in enumerate(picks[:12]):
            if cols[i % len(cols)].button(name, key=f"pick_{i}"):
                st.session_state.live_company = name

    company_l = st.text_input(
        "Prospect company", key="live_company",
        placeholder="e.g. Infosys, Razorpay, Zoho — any real company",
    )
    c1, c2 = st.columns(2)
    reflect_l = c1.checkbox(
        "Use reflection agent (draft → self-critique → revise)", key="l_reflect",
        help="The agent critiques its own draft against the fetched signals and revises if it "
             "finds an unsupported claim. Costs extra calls; shows the critique trace.",
    )
    rerank_l = c2.checkbox(
        "Rank signals by relevance (embeddings)", key="l_rerank",
        help="Reorders fetched signals most-security-relevant first before briefing.",
    )

    if st.button("Fetch signals & brief", type="primary", key="live_btn") and company_l:
        with st.spinner(f"Fetching live signals for {company_l}…"):
            res = live.live_context(company_l, mode="embedding" if rerank_l else "keyword")
        st.caption(" · ".join(res.notes) if res.notes else "")
        if res.signals:
            st.subheader(f"Live signals ({len(res.signals)})")
            render_signal_cards(res.signals)
        else:
            st.info(
                "No live signals found for this company right now (no recent breach/CVE/news hit). "
                "The brief below falls back to generic discovery — it won't invent an incident. "
                "Tip: a NewsAPI key widens coverage; NVD (CVEs) works keyless."
            )
        st.divider()
        st.subheader("Brief")
        with st.spinner("Writing the brief…"):
            if reflect_l:
                render_agent_result(generate_brief_reflective(company_l, res.context))
            else:
                render_brief(safe_generate(company_l, res.context))

# ---- 2. WATCHLIST (stored signals) -----------------------------------------------
with watchlist_tab:
    counts = counts_by_company()
    if not counts:
        st.info(
            "No signals stored yet. This mode reads a local signal database "
            "(`python -m ingest.run_ingest` to populate it). On the public demo it's empty by "
            "design — use **Live brief** to fetch on any company, or **Paste your own** for raw text."
        )
    else:
        options = sorted(counts.keys())
        company = st.selectbox(
            "Tracked company", options,
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
            with st.spinner("Thinking…"):
                render_brief(safe_generate(company, context))

# ---- 3. PASTE YOUR OWN -----------------------------------------------------------
with paste_tab:
    company_p = st.text_input("Prospect company", placeholder="e.g. Razorpay", key="p_company")
    context_p = st.text_area(
        "What you know (paste anything: news, breach reports, CVEs, notes)",
        height=180, placeholder="Paste raw signals here.", key="p_context",
    )
    reflect = st.checkbox(
        "Use reflection agent (draft → self-critique → revise)", key="p_reflect",
        help="Phase 4: the agent critiques its own draft against the context and revises if it "
             "finds an unsupported claim. Costs extra calls; shows the critique trace.",
    )
    if st.button("Generate brief", type="primary", key="p_btn") and company_p:
        with st.spinner("Thinking…"):
            if reflect:
                render_agent_result(generate_brief_reflective(company_p, context_p))
            else:
                render_brief(safe_generate(company_p, context_p))
