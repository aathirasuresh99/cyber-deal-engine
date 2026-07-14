# Cyber Deal Engine

Turns cybersecurity signals into pre-meeting sales briefs for cybersecurity sales reps.
Given a prospect company, it produces 3 key points (breach/vulnerability first), a meeting
opener, and 3 objection questions — grounded in real signals, never fabricated.

> Status: **signal pipeline + evaluation harness working.** Ingests real CVE (NVD) and news
> (NewsAPI) signals, stores and retrieves them per company, generates a structured brief, and
> scores brief quality with an automated eval harness (deterministic guardrails + LLM-as-judge).
> Agents and richer retrieval come next (see `Cyber-Deal-Engine-Build-Guide.md`).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # then paste your real keys into .env
```

Smoke-test the generator (needs a real key):
```bash
python -m src.brief
```

Run the demo UI:
```bash
streamlit run app.py
```

## Structure (grows over the build)

```
src/
  llm.py       # model wrapper (OpenAI generate + lazy Anthropic judge client)
  schema.py    # Brief output contract (Pydantic)
  brief.py     # structured generation + hallucination guardrail
  store.py     # SQLAlchemy signal storage (dedup by url)
  retrieve.py  # per-company retrieval + noise filtering
  config.py    # geo-agnostic market profile
ingest/
  nvd.py       # CVE ingester (NVD 2.0, keyless)
  news.py      # news ingester (NewsAPI)
  run_ingest.py# watchlist runner over data/target_companies.csv
eval/
  golden.jsonl        # hand-built golden dataset (fictional companies)
  checks.py           # deterministic guardrails (no fabricated CVE / forbidden facts)
  judge.py            # LLM-as-judge (OpenAI or Claude, provider-selectable)
  run_eval.py         # main harness -> results.json
  compare_models.py   # multi-model, multi-pass cost vs. quality comparison
app.py         # Streamlit demo (watchlist + paste-your-own tabs)
data/          # target_companies.csv (your sandbox watchlist)
```

## Evaluation — how quality is measured

The product's one non-negotiable rule is *never fabricate a breach, CVE, date, or number*. To
hold that rule honestly, quality is measured, not asserted. The harness runs every case in a
golden dataset through two layers:

**Deterministic checks** (`eval/checks.py`) — free, fast, and never flaky. They verify the model
detected signal vs. no-signal correctly, never echoed a forbidden fact (e.g. an unrelated
company's name or numbers), and never invented a `CVE-` id absent from the context.

**LLM-as-judge** (`eval/judge.py`) — scores the softer qualities the checks can't: faithfulness,
relevance, and actionability (1–5), plus a list of any unsupported claims. To avoid a model
grading its own homework, the judge is provider-selectable: set `JUDGE_MODEL=claude-sonnet-5` to
have **Claude grade OpenAI's output** — a genuinely independent grader.

The headline metric is the **no-hallucination rate** (share of briefs that break none of the
fabrication guards). Results are written to `eval/results.json` so runs are comparable over time.

```bash
python -m eval.run_eval          # score the golden set -> results.json
python -m eval.compare_models    # compare candidate models on cost vs. quality
```

### What the eval caught (and fixed)

The first run scored a perfect no-hallucination rate but only 4.3/5 faithfulness. The judge
localized the gap to no-signal cases: the model correctly flagged "no signal," yet its discovery
questions still *speculated* about budget, compliance readiness, and breach implications the
context never stated. One targeted prompt change — forbidding inference from unrelated facts
across every field — lifted faithfulness to **5.0/5** with the no-hallucination rate unchanged.
(See `DECISIONS.md` and `eval/results_baseline.json` for the before/after.)

### Choosing the model on evidence

Running the golden set through both models, with a fixed judge and three passes each to control
for run-to-run noise:

| model | no-hallucination | signal accuracy | faithfulness (mean ± sd) | cost / brief |
|---|---|---|---|---|
| gpt-4o | 1.0 | 1.0 | 4.67 ± 0.31 | $0.0033 |
| gpt-4o-mini | 1.0 | 1.0 | 4.9 ± 0.0 | **$0.0002** |

`gpt-4o-mini` matches the guardrails, is at least as faithful (and more stable across passes),
and costs ~17× less — so it's the production default. The variance columns matter: a single pass
had gpt-4o scoring anywhere from 4.4 to 5.0, which is why the decision rests on multi-pass numbers.

## Design decisions
See `DECISIONS.md` for scope choices and *why* (target market, coverage model, sources, hero insight).

## Roadmap
See `Cyber-Deal-Engine-Roadmap.md`/`.docx` and `Cyber-Deal-Engine-Build-Guide.md`.
