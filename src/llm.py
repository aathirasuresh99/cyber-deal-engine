"""Thin model wrapper so the rest of the app never talks to a vendor SDK directly.
Keeping this boundary makes it trivial to add Claude/Gemini and swap models in Phase 3."""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # reads OPENAI_API_KEY / ANTHROPIC_API_KEY from .env

_client = OpenAI()  # picks up OPENAI_API_KEY from the environment

# gpt-4o-mini chosen over gpt-4o via eval evidence (2026-07): identical no-hallucination
# rate (1.0) and signal accuracy (1.0), faithfulness within noise, at ~17x lower cost.
# See eval/model_comparison.json and DECISIONS.md.
DEFAULT_MODEL = "gpt-4o-mini"


def complete(prompt: str, model: str = DEFAULT_MODEL, system: str = "") -> str:
    """Plain text completion. Used for quick calls (e.g. the LLM-judge later)."""
    resp = _client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system or "You are a concise assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content


def client() -> OpenAI:
    """Expose the raw client for structured-output parsing in brief.py."""
    return _client


# Anthropic is created lazily so the app still runs with only an OPENAI_API_KEY.
# It's used as a *different-provider* judge in Phase 3 (see eval/judge.py): grading OpenAI's
# output with Claude removes the "model grading its own homework" bias.
_anthropic = None


def anthropic_client():
    """Lazy Anthropic client. Raises only if actually used without an ANTHROPIC_API_KEY."""
    global _anthropic
    if _anthropic is None:
        from anthropic import Anthropic  # local import so the dep is optional
        _anthropic = Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    return _anthropic
