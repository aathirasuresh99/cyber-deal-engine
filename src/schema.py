"""The Brief is the product's core output contract. Forcing a schema (not free text)
is what makes the output usable downstream and evaluable in Phase 3.

Phase 5 broadens the notion of a "signal" from breach/vuln-only to the full set of cyber
BUYING TRIGGERS a rep can open a conversation with. The never-fabricate rule is unchanged:
every trigger must trace to a real, cited event in the context — broadening what *counts* as a
sellable trigger does NOT loosen the ban on inventing events. See DECISIONS.md.
"""
from enum import Enum
from typing import List
from pydantic import BaseModel, Field


class Trigger(str, Enum):
    """A cyber buying trigger — a reason a company starts (or is pushed) to buy security now.
    Ordered by sales urgency: earlier members are the stronger hero for an opener."""
    BREACH = "breach_or_incident"          # confirmed breach, ransomware, leak, phishing compromise
    VULNERABILITY = "disclosed_vulnerability"  # a CVE / disclosed vulnerability affecting the company
    COMPLIANCE = "compliance_pressure"     # regulation/fine/audit deadline (DPDP, GDPR, PCI, HIPAA, RBI)
    PEER_BREACH = "peer_or_industry_breach"  # a peer/competitor/industry breach -> board asks questions
    MA_FUNDING = "ma_or_fundraising"       # M&A or fundraise -> security due diligence
    GROWTH = "growth_or_change"            # scaling, cloud migration, new SaaS, remote/new-market expansion
    DEAL_DEMAND = "customer_security_demand"  # customer/partner requires SOC 2 / security questionnaire
    INSURER_BOARD = "insurer_or_board_pressure"  # cyber-insurance renewal, auditor/board mandate
    VISIBILITY = "visibility_gap"          # complexity: can't see own data/risk/access


# Sales-urgency order used to pick the hero trigger for the opener/first key point.
TRIGGER_PRIORITY: List[Trigger] = [
    Trigger.BREACH, Trigger.VULNERABILITY, Trigger.COMPLIANCE, Trigger.PEER_BREACH,
    Trigger.MA_FUNDING, Trigger.GROWTH, Trigger.DEAL_DEMAND, Trigger.INSURER_BOARD,
    Trigger.VISIBILITY,
]

# Human-readable labels for the UI.
TRIGGER_LABELS = {
    Trigger.BREACH: "Breach / incident",
    Trigger.VULNERABILITY: "Disclosed vulnerability",
    Trigger.COMPLIANCE: "Compliance pressure",
    Trigger.PEER_BREACH: "Peer / industry breach",
    Trigger.MA_FUNDING: "M&A / fundraising",
    Trigger.GROWTH: "Growth / change",
    Trigger.DEAL_DEMAND: "Customer security demand",
    Trigger.INSURER_BOARD: "Insurer / board pressure",
    Trigger.VISIBILITY: "Visibility gap",
}


class Brief(BaseModel):
    company: str = Field(..., description="The prospect company the brief is about")

    # The buying triggers detected in the context, ordered most-urgent-first. Each MUST be
    # grounded in a real, cited event in the context — never inferred from nothing. Empty when
    # the context contains no sellable trigger.
    triggers: List[Trigger] = Field(
        default_factory=list,
        description="Buying triggers found in the context, ordered by urgency (breach first). "
                    "Include a trigger ONLY if a real event in the context supports it. "
                    "Empty if the context contains no actionable trigger.",
    )

    why_now: str = Field(
        ..., description="One line stating WHY NOW — the compelling event/trigger that gives the rep "
                         "a reason to reach out today. MUST be grounded in a real cited trigger. If "
                         "has_signal=false, say there is no current trigger and this is cold discovery.",
    )
    key_points: List[str] = Field(
        ..., min_length=3, max_length=3,
        description="Exactly 3 sharp, security-relevant facts a rep can use. Lead with the "
                    "highest-urgency trigger (a breach beats a vulnerability beats a compliance "
                    "deadline beats a peer breach beats M&A/growth). Each point must trace to the context.",
    )
    opener: str = Field(
        ..., description="One strong opening line for the meeting, anchored to the most urgent trigger",
    )
    stakeholders: List[str] = Field(
        ..., min_length=2, max_length=4,
        description="2-4 LIKELY roles to engage and why, inferred from the company's sector and the "
                    "trigger (e.g. 'CISO — owns breach response', 'DPO — accountable for DPDP'). These "
                    "are ROLE-based suggestions, NOT named individuals and NOT asserted facts about the "
                    "company's actual org. Never invent a person's name or claim who works there.",
    )
    discovery_questions: List[str] = Field(
        ..., min_length=3, max_length=3,
        description="Exactly 3 questions the rep should ASK to uncover what the signals don't show: "
                    "current security stack/tools, the cost/impact of the pain, and budget/timing. "
                    "Phrase as open questions — they must not assert any fact the context lacks.",
    )
    objection_questions: List[str] = Field(
        ..., min_length=3, max_length=3,
        description="Exactly 3 likely buyer objections, framed as questions the rep should be ready for",
    )
    has_signal: bool = Field(
        ..., description="True if the context contains at least one actionable buying trigger "
                         "(see the Trigger enum) grounded in a real event. False if the context "
                         "has no such trigger — in which case the brief must not assert any "
                         "specific event and `triggers` must be empty.",
    )
