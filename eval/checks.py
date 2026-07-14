"""Deterministic checks — cheap, fast, no LLM, no cost.

These run before the LLM judge and catch the failures that don't need judgement: did the model
get has_signal right, did it echo a forbidden fact (a fabrication trap), did it invent a CVE id
that wasn't in the context. Deterministic checks are the backbone of a trustworthy eval — they're
free, they never flake, and they define hallucination precisely instead of leaving it to opinion.
"""
from __future__ import annotations

import re
from typing import Dict

from src.schema import Brief

_CVE_RE = re.compile(r"CVE-\d{4}-\d+", re.IGNORECASE)


def _brief_text(brief: Brief) -> str:
    """All human-readable fields of a brief flattened into one searchable string.
    Includes the Phase 5 fields (why_now, stakeholders, discovery_questions) so the deterministic
    fabrication guards scan the whole brief, not just the original three fields."""
    return " ".join([
        brief.why_now, *brief.key_points, brief.opener,
        *brief.stakeholders, *brief.discovery_questions, *brief.objection_questions,
    ])


def run_checks(case: dict, brief: Brief) -> Dict[str, bool]:
    """Return a dict of check_name -> passed. All True means the brief is deterministically clean."""
    text = _brief_text(brief)
    text_lc = text.lower()
    context = case.get("context", "")

    # 1. Did the model correctly decide whether there was a real signal?
    has_signal_correct = brief.has_signal == case["expect_has_signal"]

    # 2. Did it avoid every forbidden string? (e.g. facts belonging to an unrelated company.)
    forbidden = case.get("forbidden", [])
    no_forbidden = not any(f.lower() in text_lc for f in forbidden)

    # 3. Did it avoid inventing a CVE id when the context contained none?
    context_has_cve = bool(_CVE_RE.search(context))
    brief_has_cve = bool(_CVE_RE.search(text))
    no_fabricated_cve = context_has_cve or not brief_has_cve

    return {
        "has_signal_correct": has_signal_correct,
        "no_forbidden": no_forbidden,
        "no_fabricated_cve": no_fabricated_cve,
    }


def is_clean(check_results: Dict[str, bool]) -> bool:
    """A case is a 'no-hallucination' pass only if it broke none of the fabrication guards.

    has_signal_correct is an accuracy metric, tracked separately; the hallucination guards are
    no_forbidden and no_fabricated_cve — asserting things the context never supported."""
    return check_results["no_forbidden"] and check_results["no_fabricated_cve"]
