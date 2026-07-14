"""Multi-model comparison — pick the generator on evidence, not vibes.

Runs the same golden set through several generator models, scores each with the SAME
deterministic checks and the SAME fixed judge (so the scale is identical), and captures real
token usage to compute cost. Output is a side-by-side table of quality vs. cost — the artifact
that turns "which model?" into a defensible product decision.

The judge model is held fixed on purpose: if the judge changed per row, faithfulness scores
wouldn't be comparable. Cost here is generation cost only (the judge cost is the same for every
row and isn't part of the production bill).

Run (needs OPENAI_API_KEY in .env):
    python -m eval.compare_models
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.llm import client  # noqa: E402
from src.schema import Brief  # noqa: E402
from src.brief import build_system  # noqa: E402
from src.config import ACTIVE_MARKET  # noqa: E402
from eval import checks as C  # noqa: E402
from eval.judge import judge_brief  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden.jsonl"
OUT = Path(__file__).resolve().parent / "model_comparison.json"

# Generator models to compare. Add or remove freely.
CANDIDATE_MODELS = ["gpt-4o", "gpt-4o-mini"]

# Judge is FIXED so faithfulness is measured on one consistent scale across all rows.
JUDGE_MODEL = "gpt-4o"

# Generation runs at temperature > 0, so a single pass is noisy. Repeat each model this many
# times and report faithfulness as mean +/- spread, so decisions rest on stable numbers.
REPEATS = 3

# USD per 1,000,000 tokens (input, output). Verify against the live pricing page before quoting.
# Source: OpenAI pricing, confirmed 2026-07.
PRICING = {
    "gpt-4o": {"in": 2.50, "out": 10.00},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
}


def load_cases() -> list[dict]:
    with open(GOLDEN, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def generate_with_usage(company: str, context: str, model: str):
    """Generate a Brief AND return token usage, so we can price the run. Returns (brief, in_tok, out_tok)."""
    resp = client().chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": build_system(ACTIVE_MARKET)},
            {"role": "user", "content": f"Company: {company}\n\nContext:\n{context or '(no signals provided)'}"},
        ],
        response_format=Brief,
        temperature=0.2,
    )
    u = resp.usage
    return resp.choices[0].message.parsed, u.prompt_tokens, u.completion_tokens


def cost_usd(model: str, in_tok: int, out_tok: int) -> float:
    p = PRICING.get(model)
    if not p:
        return 0.0
    return (in_tok / 1_000_000) * p["in"] + (out_tok / 1_000_000) * p["out"]


def _one_pass(model: str, cases: list[dict]) -> dict:
    """One full pass over the golden set for one model. Returns per-pass aggregates + token totals."""
    clean_flags, signal_flags, faiths = [], [], []
    tot_in = tot_out = 0
    errors = 0
    for case in cases:
        try:
            brief, in_tok, out_tok = generate_with_usage(case["company"], case["context"], model)
        except Exception:  # noqa: BLE001 - one bad case shouldn't sink the whole pass
            errors += 1
            continue
        tot_in += in_tok
        tot_out += out_tok

        chk = C.run_checks(case, brief)
        clean_flags.append(C.is_clean(chk))
        signal_flags.append(chk["has_signal_correct"])
        try:
            verdict = judge_brief(case["context"], brief, model=JUDGE_MODEL)
            faiths.append(verdict.faithfulness)
        except Exception:  # noqa: BLE001 - judge flake shouldn't kill the pass
            pass

    n = len(clean_flags)
    return {
        "n": n,
        "errors": errors,
        "no_hallucination_rate": sum(clean_flags) / n if n else None,
        "has_signal_accuracy": sum(signal_flags) / n if n else None,
        "faithfulness_avg": sum(faiths) / len(faiths) if faiths else None,
        "tokens": tot_in + tot_out,
        "in_tok": tot_in,
        "out_tok": tot_out,
    }


def evaluate_model(model: str, cases: list[dict], repeats: int = REPEATS) -> dict:
    """Run `repeats` full passes and report faithfulness as mean +/- spread across passes."""
    passes = [_one_pass(model, cases) for _ in range(repeats)]
    faith_per_pass = [p["faithfulness_avg"] for p in passes if p["faithfulness_avg"] is not None]
    in_tok = sum(p["in_tok"] for p in passes)
    out_tok = sum(p["out_tok"] for p in passes)
    total_cost = cost_usd(model, in_tok, out_tok)
    briefs = sum(p["n"] for p in passes)

    def _avg(key):
        vals = [p[key] for p in passes if p[key] is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "model": model,
        "repeats": repeats,
        "cases_errored": sum(p["errors"] for p in passes),
        "no_hallucination_rate": _avg("no_hallucination_rate"),
        "has_signal_accuracy": _avg("has_signal_accuracy"),
        "faithfulness_mean": round(statistics.mean(faith_per_pass), 2) if faith_per_pass else None,
        "faithfulness_stdev": round(statistics.stdev(faith_per_pass), 2) if len(faith_per_pass) > 1 else 0.0,
        "faithfulness_per_pass": [round(f, 2) for f in faith_per_pass],
        "cost_per_brief_usd": round(total_cost / briefs, 5) if briefs else None,
        "total_cost_usd": round(total_cost, 5),
    }


def main() -> None:
    cases = load_cases()
    rows = [evaluate_model(m, cases) for m in CANDIDATE_MODELS]
    OUT.write_text(json.dumps({"judge_model": JUDGE_MODEL, "rows": rows}, indent=2))

    print("\n=== Cyber Deal Engine — model comparison ===")
    print(f"(judge held fixed at {JUDGE_MODEL}; {REPEATS} passes/model; cost is generation only)\n")
    hdr = f"{'model':<14}{'no-halluc':>10}{'signal-acc':>12}{'faith/5 (mean±sd)':>20}{'$/brief':>10}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        faith = f"{r['faithfulness_mean']} ± {r['faithfulness_stdev']}"
        print(f"{r['model']:<14}{str(r['no_hallucination_rate']):>10}{str(r['has_signal_accuracy']):>12}"
              f"{faith:>20}{r['cost_per_brief_usd']:>10}")
        print(f"{'':>14}per-pass faithfulness: {r['faithfulness_per_pass']}")
    print(f"\nFull results written to {OUT.name}")


if __name__ == "__main__":
    main()
