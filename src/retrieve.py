"""Retrieval — turn stored raw signals into clean, relevant context for a brief.

Two composable stages, in this order:

  1. PRECISION FILTER (always on) — a keyword-relevance guard that removes the biggest source of
     noise. NVD searches are bare keyword lookups, so searching the company name "CRED" also
     matches "credential" in unrelated CVEs. We keep an NVD signal only if it genuinely names the
     company. News signals are already company-scoped by their query, so they pass through. This
     stage is about *correctness* — it drops signals that aren't really about the prospect.

  2. SEMANTIC RERANK (opt-in) — of the signals that survive the filter, order the most
     security-relevant first (a disclosed breach/CVE ahead of a generic mention), using
     embeddings. This stage is about *usefulness* — when a company has more signals than fit in
     the context window, the hero signal should lead. It NEVER invents or drops correctness; it
     only reorders what the filter kept, and falls back to recency order if embeddings are
     unavailable.

Why rerank *after* filtering, never instead of it: similarity is a soft signal and would happily
rank an unrelated-but-topically-similar CVE highly. The hard company-name filter has to run first
so the reranker only ever sorts genuinely-relevant items. Filter for truth, then rank for
relevance.

Reranking is opt-in via RETRIEVAL_MODE=embedding (default "keyword") because it costs an
embedding call and, for a bounded watchlist with few signals per company, recency order is often
fine. See DECISIONS.md.
"""
from __future__ import annotations

import math
import os
import re
from typing import Callable, List, Optional, Sequence

from src.config import ACTIVE_MARKET, MarketProfile
from src.store import get_signals, Signal

RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "keyword")  # "keyword" | "embedding"


def _mentions_company(sig: Signal, company: str) -> bool:
    """Whole-word, case-insensitive match. '\\bCRED\\b' matches "CRED breach" but not
    "credential", which is exactly the false positive we want to drop."""
    pattern = r"\b" + re.escape(company) + r"\b"
    return re.search(pattern, f"{sig.title} {sig.body}", flags=re.IGNORECASE) is not None


# A second, harder NVD false positive: a CVE in a third-party CMS/e-commerce plugin whose *title*
# happens to contain the company name — e.g. "Razorpay Payment Links for WooCommerce" or "Zoho CRM
# Client Portal plugin for WordPress". These name the company but are NOT vulnerabilities in the
# prospect's own product; for a SaaS/fintech prospect they're name-collision noise. The reliable
# tell is that the description names a plugin ecosystem (WordPress/WooCommerce/etc.). Heuristic by
# design — it assumes the prospect is not itself a CMS-plugin vendor (true for the watchlist).
_PLUGIN_PLATFORM_RE = re.compile(
    r"\b(wordpress|woocommerce|drupal|joomla|magento|typo3|prestashop|shopify)\b",
    re.IGNORECASE,
)


def is_plugin_collision(sig: Signal) -> bool:
    """True if an NVD hit looks like a third-party CMS/e-commerce plugin (name-collision noise)."""
    return bool(_PLUGIN_PLATFORM_RE.search(f"{sig.title} {sig.body}"))


def relevant_signals(company: str, limit: int = 50) -> List[Signal]:
    """Stage 1 — precision filter. Keep news as-is; keep NVD only when it names the company AND is
    not a third-party CMS/e-commerce plugin collision."""
    kept: List[Signal] = []
    for sig in get_signals(company, limit):
        if sig.source == "nvd" and (not _mentions_company(sig, company) or is_plugin_collision(sig)):
            continue
        kept.append(sig)
    return kept


# --- Stage 2: semantic rerank -------------------------------------------------

def _relevance_query(company: str, profile: MarketProfile) -> str:
    """The 'ideal signal' we rank against: this prospect + the market's weakness vocabulary.
    Signals about a breach/CVE/leak score higher than a generic name-drop."""
    kws = ", ".join(profile.breach_keywords) if profile.breach_keywords else \
        "data breach, vulnerability, incident, disclosed CVE, regulatory fine"
    return f"Cybersecurity weakness or incident affecting {company}: {kws}"


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def rank_by_relevance(
    company: str,
    signals: List[Signal],
    profile: MarketProfile = ACTIVE_MARKET,
    embed_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
) -> List[Signal]:
    """Reorder signals most-security-relevant first via embedding similarity to a relevance query.

    Fail-safe by design: if there are 0/1 signals, or embeddings error out (no key, network), the
    input order is returned unchanged — reranking is an enhancement, never a point of failure.
    `embed_fn` is injectable so this is testable offline without a live API call.
    """
    if len(signals) < 2:
        return signals
    if embed_fn is None:
        from src.llm import embed_texts as embed_fn  # lazy: no API dep unless actually reranking
    try:
        query = _relevance_query(company, profile)
        vectors = embed_fn([query] + [s.as_context_line() for s in signals])
        qv, svs = vectors[0], vectors[1:]
        scored = sorted(zip(signals, svs), key=lambda pair: _cosine(qv, pair[1]), reverse=True)
        return [sig for sig, _ in scored]
    except Exception:  # noqa: BLE001 - any embedding failure degrades to the given order
        return signals


def build_context(
    company: str,
    limit: int = 15,
    profile: MarketProfile = ACTIVE_MARKET,
    mode: Optional[str] = None,
) -> str:
    """Relevance-filtered (and, in embedding mode, reranked) context for generate_brief()."""
    kept = relevant_signals(company, limit)
    if (mode or RETRIEVAL_MODE) == "embedding":
        kept = rank_by_relevance(company, kept, profile)
    return "\n\n".join(s.as_context_line() for s in kept)


def retrieval_report(company: str) -> dict:
    """Transparency helper: raw vs relevant counts, and how much NVD noise we filtered."""
    raw = get_signals(company, 200)
    kept = relevant_signals(company, 200)
    return {
        "raw": len(raw),
        "relevant": len(kept),
        "dropped_nvd_noise": len(raw) - len(kept),
        "mode": RETRIEVAL_MODE,
    }
