"""Retrieval — turn stored raw signals into clean, relevant context for a brief.

This is retrieval v0: a keyword-relevance filter that removes the biggest source of noise in
our signals. NVD searches are bare keyword lookups, so searching the company name "CRED" also
matches the word "credential" in unrelated CVEs. We keep an NVD signal only if it genuinely
names the company. News signals are already company-scoped by their query, so they pass
through.

Embeddings-based semantic retrieval is the planned next upgrade; this heuristic makes briefs
usable today and gives a precision baseline to beat later.
"""
from __future__ import annotations

import re
from typing import List

from src.store import get_signals, Signal


def _mentions_company(sig: Signal, company: str) -> bool:
    """Whole-word, case-insensitive match. '\\bCRED\\b' matches "CRED breach" but not
    "credential", which is exactly the false positive we want to drop."""
    pattern = r"\b" + re.escape(company) + r"\b"
    return re.search(pattern, f"{sig.title} {sig.body}", flags=re.IGNORECASE) is not None


def relevant_signals(company: str, limit: int = 50) -> List[Signal]:
    """Keep news as-is; keep NVD only when it actually names the company."""
    kept: List[Signal] = []
    for sig in get_signals(company, limit):
        if sig.source == "nvd" and not _mentions_company(sig, company):
            continue
        kept.append(sig)
    return kept


def build_context(company: str, limit: int = 15) -> str:
    """Relevance-filtered context string ready to hand to generate_brief()."""
    return "\n\n".join(s.as_context_line() for s in relevant_signals(company, limit))


def retrieval_report(company: str) -> dict:
    """Transparency helper: raw vs relevant counts, and how much NVD noise we filtered."""
    raw = get_signals(company, 200)
    kept = relevant_signals(company, 200)
    return {
        "raw": len(raw),
        "relevant": len(kept),
        "dropped_nvd_noise": len(raw) - len(kept),
    }
