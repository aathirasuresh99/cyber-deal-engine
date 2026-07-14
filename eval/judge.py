"""LLM-as-judge — scores brief quality the deterministic checks can't.

Deterministic checks catch hard fabrications; a judge scores softer qualities: is every claim
actually supported by the context (faithfulness), is it on-point (relevance), could a rep act on
it (actionability). It also names any unsupported claims, which is where the real learning is.

Bias note: ideally the judge is a *different* model/provider than the writer, so it isn't
grading its own homework. The generator uses OpenAI; setting JUDGE_MODEL to a Claude model
(e.g. "claude-sonnet-5") routes judging to Anthropic — a genuinely independent grader. The
default stays gpt-4o so the harness runs with only an OpenAI key; point it at Claude once the
Anthropic key is funded for the highest-integrity scores.
"""
from __future__ import annotations

import os
from typing import List

from pydantic import BaseModel, Field

from src.llm import client, anthropic_client
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


def _brief_text(brief: Brief) -> str:
    return (
        f"Key points: {brief.key_points}\n"
        f"Opener: {brief.opener}\n"
        f"Objection questions: {brief.objection_questions}\n"
        f"has_signal flag: {brief.has_signal}"
    )


def _judge_openai(context: str, brief_text: str, model: str) -> JudgeVerdict:
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


def _judge_anthropic(context: str, brief_text: str, model: str) -> JudgeVerdict:
    """Anthropic path. Structured output is obtained via a forced tool call whose input schema
    is the JudgeVerdict schema, so Claude must return exactly the fields we validate."""
    tool = {
        "name": "record_verdict",
        "description": "Record the evaluation verdict for the brief.",
        "input_schema": JudgeVerdict.model_json_schema(),
    }
    # Note: newer Claude models reject the `temperature` param (deterministic by default), so we
    # don't set it here. Forcing the tool call already makes the output structure deterministic.
    resp = anthropic_client().messages.create(
        model=model,
        max_tokens=1024,
        system=_JUDGE_SYSTEM,
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_verdict"},
        messages=[{"role": "user",
                   "content": f"CONTEXT:\n{context or '(empty)'}\n\nBRIEF:\n{brief_text}"}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return JudgeVerdict(**block.input)
    raise RuntimeError("Anthropic response contained no tool_use block")


def judge_brief(context: str, brief: Brief, model: str = JUDGE_MODEL) -> JudgeVerdict:
    """Score one brief against its context. Routes to Anthropic for 'claude*' models, else OpenAI.
    Raises on SDK/validation error (caller handles)."""
    brief_text = _brief_text(brief)
    if model.startswith("claude"):
        return _judge_anthropic(context, brief_text, model)
    return _judge_openai(context, brief_text, model)
