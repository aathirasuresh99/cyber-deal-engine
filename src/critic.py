"""Runtime faithfulness critic — the guardrail the agent uses on itself.

Phase 3 built an *offline* judge that scores briefs against golden cases. This is the *runtime*
analog: given only a brief and the context it was allowed to use (no golden label, no forbidden
list — those don't exist for a real prospect), decide whether every claim traces back to the
context, and if not, name the offending claims so the agent can revise.

Two layers, mirroring the eval:
  1. Deterministic (free, never flakes): did the brief invent a CVE id the context never contained?
  2. LLM faithfulness pass: are there claims — a breach, a number, a misattributed event — that the
     context does not support?

Keeping this in src/ (not eval/) is deliberate: the product depends on the critic at runtime, so
the dependency points src -> critic, never src -> eval.
"""
from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel, Field

from src.llm import client, DEFAULT_MODEL
from src.schema import Brief

_CVE_RE = re.compile(r"CVE-\d{4}-\d+", re.IGNORECASE)


class Critique(BaseModel):
    """The critic's verdict on one brief."""
    faithful: bool = Field(..., description="True only if every claim in the brief is supported by the context.")
    unsupported_claims: List[str] = Field(
        default_factory=list,
        description="Specific statements in the brief not backed by the context. Empty if faithful.",
    )
    notes: str = Field("", description="One line explaining the verdict.")


def _brief_text(brief: Brief) -> str:
    return " ".join([
        brief.why_now, *brief.key_points, brief.opener,
        *brief.stakeholders, *brief.discovery_questions, *brief.objection_questions,
    ])


def deterministic_flags(context: str, brief: Brief) -> List[str]:
    """Cheap checks that need no model. Currently: fabricated-CVE detection."""
    flags: List[str] = []
    text = _brief_text(brief)
    context_has_cve = bool(_CVE_RE.search(context or ""))
    brief_cves = set(m.group(0).upper() for m in _CVE_RE.finditer(text))
    if brief_cves and not context_has_cve:
        flags.append(f"Brief cites {sorted(brief_cves)} but the context contains no CVE.")
    else:
        # Even if context has *a* CVE, flag any specific id the context doesn't contain.
        ctx_cves = set(m.group(0).upper() for m in _CVE_RE.finditer(context or ""))
        invented = brief_cves - ctx_cves
        if invented:
            flags.append(f"Brief cites CVE id(s) not in the context: {sorted(invented)}.")
    return flags


_CRITIC_SYSTEM = (
    "You are a strict fact-checker for cybersecurity sales briefs. You are given the CONTEXT a "
    "brief was allowed to use and the BRIEF that was produced. Judge the brief ONLY against the "
    "context. Flag any statement that asserts a breach, CVE, date, number, or incident not present "
    "in the context, and any security event presented as the PROSPECT's OWN that the context "
    "actually attributes to a DIFFERENT company. "
    "RISK FRAMING IS ALLOWED: stating the security RISK or implication that a real, cited event "
    "carries is reasonable interpretation, NOT an unsupported claim. This covers (a) disclosed "
    "weaknesses — an unauthenticated SQL-injection CVE 'puts customer data at risk', a disclosed "
    "vulnerability 'could be exploited'; AND (b) cited BUSINESS events used as buying triggers — a "
    "cloud migration 'widens the attack surface', an acquisition 'triggers security due diligence on "
    "both environments', a fundraise-fuelled expansion 'grows what must be secured', new SaaS/remote "
    "work 'expands the identity and access footprint'. As long as the underlying event (the CVE, the "
    "migration, the acquisition, the fundraise) is actually in the context, framing its security "
    "implication is supported. What is unsupported is asserting that an event HAPPENED when the "
    "context does not say so — e.g. claiming data WAS breached or exfiltrated when only a "
    "vulnerability or a growth event was disclosed, or stating a number, date, or CVE id the context "
    "never contained. "
    "PEER / INDUSTRY BREACH: a breach at a DIFFERENT company may appear as a legitimate "
    "peer_or_industry_breach angle — but ONLY when the brief frames it explicitly as another "
    "company's breach that raises the prospect's board-level urgency. If the brief presents another "
    "company's breach as the PROSPECT's own incident, that is misattribution and must be flagged. "
    "PRECISION — do not over-flag: before flagging a claim, confirm the fact is genuinely ABSENT "
    "from the context. If the context states an event about the prospect, a brief that repeats that "
    "event is SUPPORTED — even when the context also mentions other, unrelated companies. Multiple "
    "company names in the context do NOT make the prospect's own in-context event unsupported. "
    "Example: if the context says 'Quill Health confirmed a data breach' amid unrelated funding news "
    "about other firms, a brief stating 'Quill Health confirmed a data breach' is fully supported and "
    "must NOT be flagged. Only flag a claim about the prospect when the context does not contain it, "
    "or when the context attributes that event to a DIFFERENT company. When unsure whether a claim is "
    "present in the context, re-read the context before deciding, and do not flag a claim that is in fact there. "
    "A generic compliance angle (whichever regime fits the company's region, e.g. GDPR, SOC 2, "
    "HIPAA, DPDP) stated as background is acceptable and is NOT "
    "unsupported. "
    "GUIDANCE vs FACT: the brief also contains role-based STAKEHOLDER suggestions (e.g. 'CISO — owns "
    "breach response') and DISCOVERY QUESTIONS the rep should ask. These are advice, not assertions "
    "about the company — flag them ONLY if they invent a specific fact: a named individual, or a "
    "breach/tool/number the context never stated (including a question that presupposes such a fact). "
    "Naming a generic role or asking an open question is NOT an unsupported claim. "
    "If the context is empty, only fully generic discovery language is faithful; any "
    "specific asserted fact is unsupported."
)


def llm_critique(company: str, context: str, brief: Brief, model: str = DEFAULT_MODEL) -> Critique:
    """Structured faithfulness pass. Returns a validated Critique."""
    resp = client().chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": _CRITIC_SYSTEM},
            {"role": "user",
             "content": f"PROSPECT: {company}\n\nCONTEXT:\n{context or '(empty)'}\n\n"
                        f"BRIEF:\n{_brief_text(brief)}"},
        ],
        response_format=Critique,
        temperature=0.0,  # checking should be as deterministic as possible
    )
    return resp.choices[0].message.parsed


def critique(company: str, context: str, brief: Brief, model: str = DEFAULT_MODEL) -> Critique:
    """Full critic: deterministic flags merged with the LLM faithfulness pass.
    A deterministic flag forces faithful=False even if the LLM missed it."""
    det = deterministic_flags(context, brief)
    verdict = llm_critique(company, context, brief, model)
    if det:
        merged = list(dict.fromkeys(det + verdict.unsupported_claims))  # dedupe, preserve order
        return Critique(
            faithful=False,
            unsupported_claims=merged,
            notes=(verdict.notes + " | deterministic: fabricated CVE").strip(" |"),
        )
    return verdict
