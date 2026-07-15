"""On-demand live retrieval — the real-time path.

The watchlist path (ingest -> store -> retrieve) pre-collects signals on a schedule. That's ideal
for a fixed set of accounts, but it can't answer "brief me on THIS company, right now" for a
prospect that was never ingested — and on an ephemeral host (Streamlit Cloud) a stored DB doesn't
survive a restart anyway. This module is the answer: given a company name, it queries the same
sources LIVE (NVD keyless + NewsAPI), applies the SAME precision filter and optional rerank as the
stored path, and returns context ready for generate_brief() — with no dependency on a persisted DB.

Design contract, identical to retrieve.py so behaviour matches whether signals are stored or live:
  1. PRECISION FILTER (always) — keep news as-is (already company-scoped by its query); keep an
     NVD hit only when it genuinely names the company (drops the "CRED" -> "credential" noise).
  2. SEMANTIC RERANK (opt-in) — reorder survivors most-security-relevant first via embeddings.

Never-fabricate is unchanged: this only gathers real, cited items; the generator still refuses to
assert anything the context doesn't contain. If a source key is missing or a call fails, that
source is skipped with a note — a live brief degrades gracefully, it never invents to fill a gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from src.config import ACTIVE_MARKET, MarketProfile
from src.retrieve import _mentions_company, is_plugin_collision, rank_by_relevance


@dataclass
class LiveSignal:
    """A signal fetched live, not from the DB. Duck-types src.store.Signal for the parts
    retrieval and the UI use (source, title, body, url, published, as_context_line)."""
    company: str
    source: str
    title: str
    url: str
    body: str = ""
    published: Optional[datetime] = None

    def as_context_line(self) -> str:
        when = self.published.date().isoformat() if self.published else "date unknown"
        head = f"[{self.source} | {when}] {self.title}"
        return f"{head}\n{self.body}".strip() if self.body else head


@dataclass
class LiveResult:
    """Everything the caller (UI or brief pipeline) needs from a live fetch."""
    company: str
    signals: List[LiveSignal] = field(default_factory=list)
    context: str = ""
    notes: List[str] = field(default_factory=list)  # per-source status: skips, errors, counts

    @property
    def has_signal(self) -> bool:
        return bool(self.signals)


def _is_recent(published: Optional[datetime], cutoff: datetime) -> bool:
    """Keep a signal if it's newer than the cutoff. Undated items are kept (the API-level date
    filter already narrowed the window; this is a defensive backstop for anything that slips through)."""
    if published is None:
        return True
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published >= cutoff


def _news_signals(company: str, profile: MarketProfile, max_records: int,
                  notes: List[str], cutoff: datetime) -> List[LiveSignal]:
    """Live NewsAPI fetch (English, since the cutoff). Skipped (not fatal) on missing key/error."""
    from ingest import news  # lazy: avoids importing requests/keys unless we actually fetch
    try:
        query = news._build_query(company, profile.breach_keywords)
        articles = news.fetch(query, max_records=max_records,
                              language="en", from_date=cutoff.date().isoformat())
    except Exception as e:  # noqa: BLE001 - a missing key or network error skips news, never crashes
        notes.append(f"news skipped: {e}")
        return []
    out: List[LiveSignal] = []
    for art in articles:
        url = art.get("url")
        if not url:
            continue
        sig = LiveSignal(
            company=company,
            source="newsapi",
            title=(art.get("title") or "")[:500],
            url=url,
            body=(art.get("description") or "")[:1000],
            published=news._parse_published(art.get("publishedAt", "")),
        )
        if _is_recent(sig.published, cutoff):
            out.append(sig)
    notes.append(f"news: {len(out)} English article(s) in window")
    return out


def _nvd_signals(company: str, results: int, notes: List[str], cutoff: datetime) -> List[LiveSignal]:
    """Live NVD fetch over the published-date window, then the company precision filter."""
    from ingest import nvd  # lazy import
    now = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%S.000"
    try:
        items = nvd.fetch(company, results=results,
                          pub_start=cutoff.strftime(fmt), pub_end=now.strftime(fmt))
    except Exception as e:  # noqa: BLE001 - NVD outage/ratelimit skips CVEs, never crashes
        notes.append(f"nvd skipped: {e}")
        return []
    out: List[LiveSignal] = []
    for item in items:
        cve = item.get("cve", {})
        cve_id = cve.get("id")
        if not cve_id:
            continue
        desc = nvd._english_description(cve)
        sig = LiveSignal(
            company=company,
            source="nvd",
            title=f"{cve_id}: {desc[:120]}" if desc else cve_id,
            url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
            body=desc,
            published=nvd._parse_published(cve.get("published", "")),
        )
        # Precision filter: bare NVD keyword search matches product/dictionary words too, and also
        # third-party CMS/e-commerce plugins that merely carry the company name in their title.
        # Recency backstop in case the API returns anything outside the requested window.
        if (_mentions_company(sig, company) and not is_plugin_collision(sig)
                and _is_recent(sig.published, cutoff)):
            out.append(sig)
    notes.append(f"nvd: {len(out)} CVE(s) naming the company in window")
    return out


def fetch_live_signals(
    company: str,
    profile: MarketProfile = ACTIVE_MARKET,
    news_max: int = 15,
    nvd_results: int = 10,
    recent_days: int = 90,
) -> List[LiveSignal]:
    """Fetch live signals for a company from all sources. News first (breach events), then NVD.
    Only English news and only signals from the last `recent_days` (~3 months) are returned."""
    notes: List[str] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
    return (_news_signals(company, profile, news_max, notes, cutoff)
            + _nvd_signals(company, nvd_results, notes, cutoff))


def live_context(
    company: str,
    profile: MarketProfile = ACTIVE_MARKET,
    mode: str = "keyword",
    news_max: int = 15,
    nvd_results: int = 10,
    persist: bool = False,
    recent_days: int = 90,
) -> LiveResult:
    """Live end-to-end: fetch -> filter -> (opt) rerank -> context string.

    Only English news and only signals from the last `recent_days` (~3 months) are used.
    `mode="embedding"` reranks survivors most-relevant-first (same as retrieve.build_context).
    `persist=True` also writes the fetched signals to the store, so a live lookup can seed the
    watchlist (deduped by url) — off by default because the primary use is ephemeral/on-demand.
    """
    notes: List[str] = [f"window: last {recent_days} days · English news only"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
    signals = (_news_signals(company, profile, news_max, notes, cutoff)
               + _nvd_signals(company, nvd_results, notes, cutoff))

    if persist and signals:
        from src.store import add_signal
        stored = 0
        for s in signals:
            if add_signal(company=s.company, source=s.source, title=s.title,
                          url=s.url, body=s.body, published=s.published):
                stored += 1
        notes.append(f"persisted {stored} new signal(s) to the store")

    if mode == "embedding" and len(signals) >= 2:
        signals = rank_by_relevance(company, signals, profile)

    context = "\n\n".join(s.as_context_line() for s in signals)
    return LiveResult(company=company, signals=signals, context=context, notes=notes)


if __name__ == "__main__":
    # Manual smoke test (needs NEWSAPI_KEY for news; NVD is keyless).
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "Infosys"
    res = live_context(name)
    print(f"{name}: {len(res.signals)} live signal(s)")
    for n in res.notes:
        print("  -", n)
    print("\n--- CONTEXT ---\n", res.context[:1500])
