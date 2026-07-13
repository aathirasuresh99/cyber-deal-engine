"""Thin model wrapper so the rest of the app never talks to a vendor SDK directly.
Keeping this boundary makes it trivial to add Claude/Gemini and swap models in Phase 3."""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # reads OPENAI_API_KEY / ANTHROPIC_API_KEY from .env

_client = OpenAI()  # picks up OPENAI_API_KEY from the environment

DEFAULT_MODEL = "gpt-4o"


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
