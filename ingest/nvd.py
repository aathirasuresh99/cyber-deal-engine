"""NVD (National Vulnerability Database) ingester — the first, easiest signal layer.

Per DECISIONS.md, sources are layered by difficulty and CVE/NVD comes first: it's a free,
public, keyless API with a clean JSON schema. This ingester does a keyword search over CVE
descriptions and stores hits as Signals.

Honest scope note: NVD is a vulnerability *catalogue*, not a company breach feed. A keyword
match means "a CVE mentions this term", not "this company was breached". Early on we search
the company name to surface CVEs that name a company/product; the news ingester carries the
breach-event load. This keeps us truthful — we never claim a match is a breach.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import List

import requests

from src.store import add_signal

NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
# NVD asks unauthenticated callers to stay under ~5 req / 30s. We sleep to be polite.
_POLITE_DELAY_S = 6.5


def _parse_published(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _english_description(cve: dict) -> str:
    for d in cve.get("descriptions", []):
        if d.get("lang") == "en":
            return d.get("value", "")
    return ""


def fetch(keyword: str, results: int = 10,
          pub_start: str | None = None, pub_end: str | None = None) -> List[dict]:
    """Return raw NVD CVE items matching a keyword. Network call; may raise on HTTP error.

    `pub_start`/`pub_end` (ISO 8601, e.g. "2026-04-15T00:00:00.000") restrict to CVEs published in
    that window — NVD requires BOTH when either is given, and caps the range at 120 days. Default
    None = no date filter, so the watchlist ingest path is unchanged; the live path passes a
    ~3-month window. NVD descriptions are already English (we select lang=='en')."""
    params: dict = {"keywordSearch": keyword, "resultsPerPage": results}
    if pub_start and pub_end:
        params["pubStartDate"] = pub_start
        params["pubEndDate"] = pub_end
    resp = requests.get(NVD_API, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("vulnerabilities", [])


def ingest_for_company(company: str, keyword: str | None = None,
                       results: int = 10) -> int:
    """Search NVD for a company (or explicit keyword) and store new CVEs. Returns # stored."""
    term = keyword or company
    stored = 0
    for item in fetch(term, results):
        cve = item.get("cve", {})
        cve_id = cve.get("id")
        if not cve_id:
            continue
        desc = _english_description(cve)
        url = f"https://nvd.nist.gov/vuln/detail/{cve_id}"
        if add_signal(
            company=company,
            source="nvd",
            title=f"{cve_id}: {desc[:120]}" if desc else cve_id,
            url=url,
            body=desc,
            published=_parse_published(cve.get("published", "")),
        ):
            stored += 1
    time.sleep(_POLITE_DELAY_S)  # rate-limit courtesy between companies
    return stored
