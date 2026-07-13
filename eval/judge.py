"""LLM-as-judge — scores brief quality the deterministic checks can't.

Deterministic checks catch hard fabrications; a judge scores softer qualities: is every claim
actually supported by the context (faithfulness), is it on-point (relevance), could a rep act on
it (actionability). It also names any unsupported claims, which is where the real learning is.

Bias note: ideally the judge is a *different* model/provider than the writer, so it isn't
grading its own homework. The generator uses OpenAI (gpt-4o); set JUDGE_MODEL to another model
(and later a different provider) once that's funded. Default stays gpt-4o so the harness runs
today with one key.
"""
from __future__ import annotations

import os
from typing import List

from pydantic import BaseModel, Field

from src.llm import client
from src.schema import Brief

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-4o")


class JudgeVerdict(BaseModel):
    faithfulness: int = Field(..., ge=1, le=5,
                              description="5 = every claim is supported by the context; "
                                          "1 = claims are invented or contradict the context.")
    relevance: int = Field(..., ge=1, le=5, description="Are the points security-relevant and on-topic?")
    actionability: int = Field(..., ge=1, le=5, description="Could a sales rep open a meeting with this?")
    unsupported_claims: List[str] = Field(
        default_factory=list,
        description="Specific statements in the brief not backed by the context. Empty if fully faithful.",
    )
    rationale: str = Field(..., description="One or two sentences explaining the faithfulness score.")


_JUDGE_SYSTEM = (
    "You are a strict evaluator of cybersecurity sales briefs. You are given the CONTEXT the "
    "brief was allowed to use and the BRIEF that was produced. Judge the brief ONLY against the "
    "context. A brief must never assert breaches, CVEs, dates, or numbers that are not in the "
    "context. Note: a generic compliance angle (e.g. DPDP, RBI) is acceptable background and is "
    "NOT an unsupported claim, but a specific fabricated incident IS. If the context is empty, a "
    "faithful brief offers only generic discovery angles and asserts no specific facts."
)


def judge_brief(context: str, brief: Brief, model: str = JUDGE_MODEL) -> JudgeVerdict:
    """Score one brief against its context. Raises on SDK/validation error (caller handles)."""
    brief_text = (
        f"Key points: {brief.key_points}\n"
        f"Opener: {brief.opener}\n"
        f"Objection questions: {brief.objection_questions}\n"
        f"has_signal flag: {brief.has_signal}"
    )
    resp = client().chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": f"CONTEXT:\n{context or '(empty)'}\n\nBRIEF:\n{brief_text}"},
        ],
        response_format=JudgeVerdict,
        temperature=0.0,  # judging should be as deterministic as possible
    )
    return resp.choices[0].message.parsed
