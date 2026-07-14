"""News ingester — the breach-event signal layer.

Source choice: NewsAPI (/v2/everything). Reliable, well-documented, and returns a real
article snippet (description) we can store as signal body. It needs a free key in
NEWSAPI_KEY (.env). We moved here from GDELT, whose free endpoint rate-limited and timed out
too aggressively to demo on command (see DECISIONS.md).

Free-tier notes: articles are limited to roughly the last month and 100 requests/day — fine
for a 10-company watchlist refreshed occasionally.

Geo-agnosticism: this ingester is driven by ACTIVE_MARKET.breach_keywords (passed in by the
runner), never by hardcoded terms. Point it at a different MarketProfile and it searches that
market's language instead.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List

import requests

from src.store import add_signal

NEWSAPI_URL = "https://newsapi.org/v2/everything"


def _api_key() -> str:
    key = os.getenv("NEWSAPI_KEY")
    if not key:
        raise RuntimeError(
            "NEWSAPI_KEY is not set. Add it to .env (get a free key at newsapi.org/register)."
        )
    return key


def _parse_published(value: str) -> datetime | None:
    # NewsAPI format: ISO 8601, e.g. 2026-05-01T12:00:00Z
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def _build_query(company: str, breach_keywords: List[str]) -> str:
    """`"Company" AND ("data breach" OR "ransomware" OR ...)` — quotes keep phrases intact,
    the AND ties every hit to the company so we don't pull generic security news."""
    terms = " OR ".join(f'"{k}"' for k in breach_keywords)
    return f'"{company}" AND ({terms})'


def fetch(query: str, max_records: int = 15, language: str | None = None,
          from_date: str | None = None) -> List[dict]:
    """Return raw NewsAPI article records for a query. Network call; may raise on HTTP/API error.

    `language` (e.g. "en") restricts results to one language; `from_date` (ISO date, e.g.
    "2026-04-15") drops anything older. Both default to None = NewsAPI's own defaults, so the
    watchlist ingest path is unchanged; the live path passes them for English + recent signals."""
    params = {
        "q": query,
        "sortBy": "publishedAt",
        "pageSize": max_records,
        "apiKey": _api_key(),
    }
    if language:
        params["language"] = language
    if from_date:
        params["from"] = from_date
    resp = requests.get(NEWSAPI_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # NewsAPI signals problems in-body with status="error" even on some 200s.
    if data.get("status") == "error":
        raise RuntimeError(f"NewsAPI error: {data.get('code')} - {data.get('message')}")
    return data.get("articles", [])


def ingest_for_company(company: str, breach_keywords: List[str],
                       max_records: int = 15) -> int:
    """Search news for the company + breach terms and store new articles. Returns # stored."""
    stored = 0
    for art in fetch(_build_query(company, breach_keywords), max_records):
        url = art.get("url")
        if not url:
            continue
        if add_signal(
            company=company,
            source="newsapi",
            title=(art.get("title") or "")[:500],
            url=url,
            body=(art.get("description") or "")[:1000],
            published=_parse_published(art.get("publishedAt", "")),
        ):
            stored += 1
    return stored
