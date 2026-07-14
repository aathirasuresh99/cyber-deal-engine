"""Reflection agent — the Phase 4 core: the brief generator that checks its own work.

Plain generation (src/brief.py) is one LLM call: context in, brief out, hope it's faithful.
Phase 3 proved that even a tuned prompt occasionally slips (e.g. pitching another company's CVE
to the prospect). A reflection agent closes that gap at *runtime* instead of only catching it
offline:

    draft ─► critique ─► (unfaithful?) ─► revise with the critique ─► critique ─► ...
                    └─ (faithful) ─► done

The critic (src/critic.py) is the same guardrail logic the eval uses, applied to the model's own
output. This is the payoff of building the eval first: the offline judge and the runtime safety
net share one definition of "faithful", so the agent is held to exactly the standard we measure.

The loop is bounded (max_revisions) so cost stays predictable, and it returns a full trace so the
behaviour is observable — you can see the draft, what was flagged, and what changed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from src.brief import generate_brief
from src.critic import critique, Critique
from src.llm import DEFAULT_MODEL
from src.config import ACTIVE_MARKET, MarketProfile
from src.schema import Brief


@dataclass
class Pass:
    """One draft-and-critique cycle, for the trace."""
    attempt: int
    faithful: bool
    unsupported_claims: List[str]
    notes: str


@dataclass
class AgentResult:
    """The final brief plus everything the loop did to get there."""
    brief: Optional[Brief]
    passes: List[Pass] = field(default_factory=list)
    revisions: int = 0
    faithful: bool = False
    error: Optional[str] = None

    @property
    def clean_first_try(self) -> bool:
        return self.faithful and self.revisions == 0


def generate_brief_reflective(
    company: str,
    context: str,
    model: str = DEFAULT_MODEL,
    profile: MarketProfile = ACTIVE_MARKET,
    max_revisions: int = 2,
) -> AgentResult:
    """Generate a brief, critique it, and revise until faithful or the revision budget is spent.

    max_revisions=0 reduces this to plain generation-plus-a-critique (no rewrite), which is a
    useful ablation for the eval. Never raises: on SDK/validation failure it returns an
    AgentResult with .error set and .brief None, so callers stay crash-free like safe_generate."""
    passes: List[Pass] = []
    try:
        draft = generate_brief(company, context, model, profile)
    except Exception as e:  # noqa: BLE001 - surface any SDK/validation error safely
        return AgentResult(brief=None, error=str(e))

    for attempt in range(max_revisions + 1):
        try:
            verdict: Critique = critique(company, context, draft, model)
        except Exception as e:  # noqa: BLE001 - a critic failure shouldn't lose the draft
            # Return the best draft we have; mark faithful unknown via error note.
            return AgentResult(brief=draft, passes=passes, revisions=attempt,
                               faithful=False, error=f"critic failed: {e}")

        passes.append(Pass(attempt=attempt, faithful=verdict.faithful,
                           unsupported_claims=verdict.unsupported_claims, notes=verdict.notes))

        if verdict.faithful:
            return AgentResult(brief=draft, passes=passes, revisions=attempt, faithful=True)

        if attempt == max_revisions:
            break  # out of budget; return the last draft, unfaithful

        feedback = "\n".join(f"- {c}" for c in verdict.unsupported_claims) or "- (unspecified)"
        try:
            draft = generate_brief(company, context, model, profile, feedback=feedback)
        except Exception as e:  # noqa: BLE001
            return AgentResult(brief=draft, passes=passes, revisions=attempt,
                               faithful=False, error=f"revision failed: {e}")

    return AgentResult(brief=draft, passes=passes, revisions=max_revisions, faithful=False)


def _format_trace(res: AgentResult) -> str:
    lines = []
    for p in res.passes:
        tag = "FAITHFUL" if p.faithful else "FLAGGED"
        lines.append(f"  attempt {p.attempt}: {tag}"
                     + ("" if p.faithful else " -> " + "; ".join(p.unsupported_claims)))
    verdict = "clean on first try" if res.clean_first_try else (
        f"faithful after {res.revisions} revision(s)" if res.faithful else
        f"still flagged after {res.revisions} revision(s)")
    return "\n".join(lines) + f"\n  result: {verdict}"


if __name__ == "__main__":
    # Manual smoke test (needs a real OPENAI_API_KEY). The misattribution trap: the CVE belongs to
    # "Larkspur Analytics", not the prospect "Larkfield" — a faithful brief must NOT pitch it.
    from dotenv import load_dotenv
    load_dotenv()

    res = generate_brief_reflective(
        "Larkfield",
        "[nvd | 2026-04-22] CVE-2026-31880: XXE injection in Larkspur Analytics Suite, CVSS 7.9. "
        "Larkspur Analytics is a separate company; the advisory does not mention Larkfield.",
    )
    print(_format_trace(res))
    if res.brief:
        print(res.brief.model_dump_json(indent=2))
