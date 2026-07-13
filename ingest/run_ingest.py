"""Ingestion runner — reads the watchlist and pulls signals for every company.

Usage (needs network; no API keys required for NVD + GDELT):
    python -m ingest.run_ingest              # all companies in the watchlist
    python -m ingest.run_ingest Razorpay     # one company by name

This is the "watchlist-first" coverage model in action: we iterate a known, bounded set of
accounts from data/target_companies.csv. Geo-agnosticism is preserved — the breach keywords
come from ACTIVE_MARKET, not from this file.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # make NEWSAPI_KEY (and any other .env vars) available to the ingesters

from src.config import ACTIVE_MARKET
from src.store import counts_by_company
from ingest import nvd, news

WATCHLIST = Path(__file__).resolve().parent.parent / "data" / "target_companies.csv"


def load_companies() -> list[str]:
    with open(WATCHLIST, newline="", encoding="utf-8") as f:
        return [row["company_name"].strip() for row in csv.DictReader(f)
                if row.get("company_name", "").strip()]


def run(companies: list[str]) -> None:
    keywords = ACTIVE_MARKET.breach_keywords
    print(f"Market: {ACTIVE_MARKET.label} | {len(companies)} companies\n")
    for company in companies:
        try:
            n_news = news.ingest_for_company(company, keywords)
        except Exception as e:  # noqa: BLE001 - one bad source shouldn't stop the run
            n_news = 0
            print(f"  ! news failed for {company}: {e}")
        try:
            n_cve = nvd.ingest_for_company(company)
        except Exception as e:  # noqa: BLE001
            n_cve = 0
            print(f"  ! nvd failed for {company}: {e}")
        print(f"  {company:<15} +{n_news} news  +{n_cve} cve")

    print("\nStored totals per company:")
    for company, n in sorted(counts_by_company().items()):
        print(f"  {company:<15} {n}")


if __name__ == "__main__":
    args = sys.argv[1:]
    run(args if args else load_companies())
