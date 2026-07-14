"""Eval harness — the spine of the project.

For every golden case: generate a brief, run deterministic checks, run the LLM judge, then
aggregate into the numbers that tell the truth about quality:

  - no-hallucination rate  (deterministic: no forbidden facts, no invented CVEs)  <- north star
  - has_signal accuracy     (did it correctly detect signal vs no-signal)
  - judge faithfulness avg  (soft, LLM-scored)

Results are written to eval/results.json so runs are comparable over time (regression tracking).

Run (needs OPENAI_API_KEY in .env):
    python -m eval.run_eval
"""
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.brief import safe_generate  # noqa: E402 (after load_dotenv)
from eval import checks as C  # noqa: E402
from eval.judge import judge_brief  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden.jsonl"
RESULTS = Path(__file__).resolve().parent / "results.json"


def load_cases() -> list[dict]:
    with open(GOLDEN, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate() -> dict:
    cases = load_cases()
    rows = []
    for case in cases:
        brief = safe_generate(case["company"], case["context"])
        if not hasattr(brief, "model_dump"):  # generation failed (e.g. quota) -> record and skip
            rows.append({"id": case["id"], "error": brief.get("error", "generation failed")})
            continue

        chk = C.run_checks(case, brief)
        try:
            verdict = judge_brief(case["context"], brief).model_dump()
        except Exception as e:  # noqa: BLE001 - a judge failure shouldn't kill the run
            verdict = {"error": str(e)}

        rows.append({
            "id": case["id"],
            "category": case["category"],
            "company": case["company"],
            "expect_has_signal": case["expect_has_signal"],
            "got_has_signal": brief.has_signal,
            "checks": chk,
            "clean": C.is_clean(chk),
            "judge": verdict,
            # Persist the actual brief so any failure is debuggable without re-running.
            "brief": {
                "key_points": brief.key_points,
                "opener": brief.opener,
                "objection_questions": brief.objection_questions,
            },
        })

    scored = [r for r in rows if "checks" in r]
    n = len(scored)
    faith = [r["judge"]["faithfulness"] for r in scored if "faithfulness" in r.get("judge", {})]
    summary = {
        "cases_total": len(rows),
        "cases_scored": n,
        "cases_errored": len(rows) - n,
        "no_hallucination_rate": round(sum(r["clean"] for r in scored) / n, 3) if n else None,
        "has_signal_accuracy": round(
            sum(r["checks"]["has_signal_correct"] for r in scored) / n, 3) if n else None,
        "judge_faithfulness_avg": round(sum(faith) / len(faith), 2) if faith else None,
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    report = evaluate()
    RESULTS.write_text(json.dumps(report, indent=2))
    s = report["summary"]
    print("\n=== Cyber Deal Engine — eval summary ===")
    print(f"cases scored:            {s['cases_scored']}/{s['cases_total']}"
          + (f"  ({s['cases_errored']} errored)" if s["cases_errored"] else ""))
    print(f"no-hallucination rate:   {s['no_hallucination_rate']}   <- north star")
    print(f"has_signal accuracy:     {s['has_signal_accuracy']}")
    print(f"judge faithfulness avg:  {s['judge_faithfulness_avg']} / 5")
    # Surface individual failures so they're actionable.
    for r in report["rows"]:
        if "error" in r:
            print(f"  ! {r['id']}: generation error - {r['error'][:60]}")
        elif not r["clean"]:
            bad = [k for k, v in r["checks"].items() if not v]
            print(f"  ✗ {r['id']} ({r['category']}): failed {bad}")
    print(f"\nFull results written to {RESULTS.name}")


if __name__ == "__main__":
    main()
