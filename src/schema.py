"""The Brief is the product's core output contract. Forcing a schema (not free text)
is what makes the output usable downstream and evaluable in Phase 3."""
from typing import List
from pydantic import BaseModel, Field


class Brief(BaseModel):
    company: str = Field(..., description="The prospect company the brief is about")

    # Hero insight = breach & vulnerability (per DECISIONS.md). These must be grounded
    # in the provided context — never invented.
    key_points: List[str] = Field(
        ..., min_length=3, max_length=3,
        description="Exactly 3 sharp, security-relevant facts a rep can use. "
                    "Lead with breach/vulnerability signals; compliance exposure is a strong second.",
    )
    opener: str = Field(
        ..., description="One strong opening line for the meeting, anchored to the most urgent signal",
    )
    objection_questions: List[str] = Field(
        ..., min_length=3, max_length=3,
        description="Exactly 3 likely buyer objections, framed as questions the rep should be ready for",
    )
    has_signal: bool = Field(
        ..., description="True only if the context contains an actionable security WEAKNESS "
                         "(breach, incident, disclosed CVE/vulnerability, or regulatory fine). "
                         "Positive posture (certifications, awards) and general business news "
                         "(funding, launches, hires) are NOT signals -> False. If False, the brief "
                         "must not assert any specific breach or fact.",
    )
