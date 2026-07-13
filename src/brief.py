"""Structured brief generation with a hallucination guardrail.
This is the Week 1 core: context in -> validated Brief out."""
from src.llm import client, DEFAULT_MODEL
from src.schema import Brief
from src.config import ACTIVE_MARKET, MarketProfile


def build_system(profile: MarketProfile) -> str:
    """Construct the system prompt from a market profile. No geography is hardcoded —
    the compliance angle comes from config, so the same logic serves any market."""
    frameworks = ", ".join(profile.compliance_frameworks)
    return (
        "You are Cyber Deal Engine, a cybersecurity sales-intelligence assistant. "
        f"Your target market is {profile.label}. "
        "Given context about a prospect company, produce a concise pre-meeting brief for a "
        "cybersecurity sales rep.\n\n"
        "RULES:\n"
        "1. Lead with breach and vulnerability signals (the hero). Treat compliance exposure "
        f"(e.g. {frameworks}) as a strong secondary angle. Keep tech-stack speculation minimal.\n"
        "2. Use ONLY facts present in the provided context. NEVER invent breaches, CVEs, dates, or numbers. "
        "Do not speculate about the company's security posture, budget, compliance readiness, or the "
        "security implications of unrelated facts (e.g. a funding round, a new office, a product launch). "
        "This rule applies to EVERY field, including the opener and the objection questions.\n"
        "3. If the context contains no real, relevant signal, set has_signal=false. In that case ALL fields "
        "(key_points, opener, objection_questions) must be fully generic discovery prompts that would apply "
        "to any prospect — they must NOT reference or draw inferences from anything mentioned in the context. "
        "Do not assert or imply any specific breach, risk, or need. A generic compliance mention "
        f"(e.g. {frameworks}) is acceptable background.\n"
        "4. Every brief: exactly 3 key points, 1 opener, 3 objection questions."
    )


# Default prompt for the active market; callers can override with their own profile.
SYSTEM = build_system(ACTIVE_MARKET)


def generate_brief(company: str, context: str, model: str = DEFAULT_MODEL,
                   profile: MarketProfile = ACTIVE_MARKET) -> Brief:
    """Call the model with structured outputs; returns a validated Brief object."""
    resp = client().chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": build_system(profile)},
            {"role": "user", "content": f"Company: {company}\n\nContext:\n{context or '(no signals provided)'}"},
        ],
        response_format=Brief,
        temperature=0.2,
    )
    return resp.choices[0].message.parsed


def safe_generate(company: str, context: str, model: str = DEFAULT_MODEL,
                  profile: MarketProfile = ACTIVE_MARKET, retries: int = 2):
    """Never crash the caller: retry, then return an error dict on persistent failure."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            return generate_brief(company, context, model, profile)
        except Exception as e:  # noqa: BLE001 - we want to surface any SDK/validation error safely
            last_err = e
    return {"error": str(last_err), "company": company}


if __name__ == "__main__":
    # Quick manual smoke test (needs a real OPENAI_API_KEY in .env).
    demo = safe_generate(
        "Acme Fintech",
        "Acme Fintech disclosed a data breach in 2025 exposing ~40k customer records. "
        "Runs on AWS. SOC 2 Type II reportedly in progress. Subject to India's DPDP Act.",
    )
    print(demo.model_dump_json(indent=2) if hasattr(demo, "model_dump_json") else demo)
