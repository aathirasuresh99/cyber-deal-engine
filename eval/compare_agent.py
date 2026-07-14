"""Ablation: does the reflection agent actually beat plain generation?

Runs every golden case two ways — plain single-pass generation vs. the draft->critique->revise
agent — and scores both with the SAME deterministic checks and LLM judge used everywhere else.
The question this answers, in numbers a PM can defend: is the extra cost of self-critique buying
real faithfulness, and does it fix cases the single pass gets wrong?

Metrics per arm:
  - no_hallucination_rate  (deterministic north star)
  - has_signal_accuracy
  - judge_faithfulness_avg

Agent-only:
  - cases_revised          (how often the critic triggered a rewrite)
  - flips_to_clean         (cases the plain arm got dirty that the agent fixed)  <- the payoff
  - flips_to_dirty         (regressions — should be 0)

Writes eval/agent_comparison.json. Costs credits: ~28 cases, plain = 1 call each, agent = up to
(1 + max_revisions) generations + a critique per pass. Judge adds one call per brief per arm.

Run (needs OPENAI_API_KEY; set JUDGE_MODEL=claude-sonnet-5 for the independent grader):
    python -m eval.compare_agent
"""
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.brief import safe_generate  # noqa: E402
from src.agent import generate_brief_reflective  # noqa: E402
from eval import checks as C  # noqa: E402
from eval.judge import judge_brief  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden.jsonl"
OUT = Path(__file__).resolve().parent / "agent_comparison.json"

MAX_REVISIONS = 2


def load_cases() -> list[dict]:
    with open(GOLDEN, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _score(case: dict, brief) -> dict:
    """Deterministic checks + judge for one brief. `brief` is a validated Brief."""
    chk = C.run_checks(case, brief)
    try:
        faith = judge_brief(case["context"], brief).faithfulness
    except Exception as e:  # noqa: BLE001 - judge failure shouldn't kill the run
        faith = None
    return {
        "has_signal_correct": chk["has_signal_correct"],
        "clean": C.is_clean(chk),
        "faithfulness": faith,
    }


def _aggregate(scores: list[dict]) -> dict:
    n = len(scores)
    faith = [s["faithfulness"] for s in scores if isinstance(s["faithfulness"], int)]
    return {
        "n": n,
        "no_hallucination_rate": round(sum(s["clean"] for s in scores) / n, 3) if n else None,
        "has_signal_accuracy": round(sum(s["has_signal_correct"] for s in scores) / n, 3) if n else None,
        "judge_faithfulness_avg": round(sum(faith) / len(faith), 2) if faith else None,
    }


def evaluate() -> dict:
    cases = load_cases()
    rows = []
    for case in cases:
        # --- plain arm ---
        plain_brief = safe_generate(case["company"], case["context"])
        if not hasattr(plain_brief, "model_dump"):
            rows.append({"id": case["id"], "error": f"plain gen failed: {plain_brief.get('error')}"})
            continue
        plain = _score(case, plain_brief)

        # --- reflective arm ---
        res = generate_brief_reflective(case["company"], case["context"], max_revisions=MAX_REVISIONS)
        if res.brief is None:
            rows.append({"id": case["id"], "error": f"agent failed: {res.error}"})
            continue
        agent = _score(case, res.brief)

        rows.append({
            "id": case["id"],
            "category": case["category"],
            "plain": plain,
            "agent": agent,
            "revisions": res.revisions,
            "agent_faithful_flag": res.faithful,
            # keep the flags the critic raised, for debugging what drove a rewrite
            "critic_passes": [
                {"attempt": p.attempt, "faithful": p.faithful, "flags": p.unsupported_claims}
                for p in res.passes
            ],
        })

    scored = [r for r in rows if "plain" in r]
    plain_scores = [r["plain"] for r in scored]
    agent_scores = [r["agent"] for r in scored]

    flips_to_clean = [r["id"] for r in scored if not r["plain"]["clean"] and r["agent"]["clean"]]
    flips_to_dirty = [r["id"] for r in scored if r["plain"]["clean"] and not r["agent"]["clean"]]
    revised = [r["id"] for r in scored if r["revisions"] > 0]

    summary = {
        "cases_scored": len(scored),
        "cases_errored": len(rows) - len(scored),
        "plain": _aggregate(plain_scores),
        "agent": _aggregate(agent_scores),
        "cases_revised": len(revised),
        "revised_ids": revised,
        "flips_to_clean": flips_to_clean,   # payoff: agent fixed a plain-arm hallucination
        "flips_to_dirty": flips_to_dirty,   # regressions (want empty)
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    report = evaluate()
    OUT.write_text(json.dumps(report, indent=2))
    s = report["summary"]
    p, a = s["plain"], s["agent"]
    print("\n=== Plain vs. Reflective agent ===")
    print(f"cases scored:            {s['cases_scored']}"
          + (f"  ({s['cases_errored']} errored)" if s["cases_errored"] else ""))
    print(f"{'metric':<26}{'plain':>8}{'agent':>8}")
    print(f"{'no-hallucination rate':<26}{p['no_hallucination_rate']!s:>8}{a['no_hallucination_rate']!s:>8}   <- north star")
    print(f"{'has_signal accuracy':<26}{p['has_signal_accuracy']!s:>8}{a['has_signal_accuracy']!s:>8}")
    print(f"{'judge faithfulness avg':<26}{p['judge_faithfulness_avg']!s:>8}{a['judge_faithfulness_avg']!s:>8}")
    print(f"\ncases the agent revised: {s['cases_revised']}  {s['revised_ids']}")
    print(f"fixed by reflection:     {len(s['flips_to_clean'])}  {s['flips_to_clean']}   <- payoff")
    if s["flips_to_dirty"]:
        print(f"REGRESSIONS:             {s['flips_to_dirty']}   <- investigate")
    print(f"\nFull results written to {OUT.name}")


if __name__ == "__main__":
    main()
