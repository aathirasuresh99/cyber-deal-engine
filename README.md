# Cyber Deal Engine

Turns cybersecurity signals into pre-meeting sales briefs for cybersecurity sales reps.
Given a prospect company, it produces 3 key points (breach/vulnerability first), a meeting
opener, and 3 objection questions — grounded in real signals, never fabricated.

> Status: **signal pipeline + evaluation harness + reflection agent working.** Ingests real CVE
> (NVD) and news (NewsAPI) signals, stores and retrieves them per company, generates a structured
> brief, scores quality with an automated eval harness (deterministic guardrails + LLM-as-judge),
> and can self-critique and revise its own drafts against that same faithfulness standard. Richer
> retrieval (embeddings/reranking) comes next (see `Cyber-Deal-Engine-Build-Guide.md`).

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
  critic.py    # runtime faithfulness critic (same standard the eval judges)
  agent.py     # reflection agent: draft -> critique -> revise
  store.py     # SQLAlchemy signal storage (dedup by url)
  retrieve.py  # per-company retrieval + noise filtering
  config.py    # geo-agnostic market profile
ingest/
  nvd.py       # CVE ingester (NVD 2.0, keyless)
  news.py      # news ingester (NewsAPI)
  run_ingest.py# watchlist runner over data/target_companies.csv
eval/
  golden.jsonl             # hand-built golden dataset (fictional companies)
  golden_adversarial.jsonl # harder slice: multi-company noise, similar names, buried signals
  checks.py                # deterministic guardrails (no fabricated CVE / forbidden facts)
  judge.py                 # LLM-as-judge (OpenAI or Claude, provider-selectable)
  run_eval.py              # main harness -> results.json
  compare_models.py        # multi-model, multi-pass cost vs. quality comparison
  compare_agent.py         # plain vs. reflection-agent ablation
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

## The reflection agent — and when it actually helps

Phase 4 turns the generator into an agent that checks its own work. Instead of one call
(context in, brief out, hope it's faithful), it runs a bounded loop:

```
draft ─► critique ─► unfaithful? ─► revise with the critique ─► critique ─► ...
                └─ faithful ─► done
```

The critic (`src/critic.py`) applies the *same* definition of "faithful" the eval judge uses, so
the agent is held at runtime to exactly the standard the eval measures offline. Building the eval
first is what made this possible — the offline judge and the runtime safety net share one rule.

```bash
python -m src.agent                                   # trace one brief through the loop
python -m eval.compare_agent                          # plain vs. agent, in-distribution
python -m eval.compare_agent golden_adversarial.jsonl # plain vs. agent, adversarial slice
```

### In-distribution: reflection did *not* beat a tuned prompt

Ablation on the 28-case golden set (Claude judge), plain single pass vs. the agent:

| metric | plain | agent |
|---|---|---|
| no-hallucination rate | 1.0 | 1.0 |
| has_signal accuracy | 1.0 | 1.0 |
| judge faithfulness avg | 4.89 | 4.96 |
| hallucinations fixed by reflection | — | **0** |

The honest result: **no hallucinations to fix.** After the Phase 3 prompt hardening the base
generator is already clean in-distribution, so the loop's north-star payoff is zero here and the
faithfulness gap (4.89 vs 4.96) is within run-to-run noise. The first ablation run also exposed a
side issue: the critic was over-firing on legitimate *risk framing* ("a disclosed SQL-injection
CVE puts customer data at risk") that the judge — correctly — accepted. That disagreement was a
finding in itself: critic and judge didn't share a boundary. Both were updated to agree — stating
the *risk* a disclosed weakness implies is allowed; asserting an event *happened* (or inventing a
fact/CVE, or misattributing another company's event) is not.

The takeaway is the point: **a reflection loop only earns its cost when the base generator
actually slips.** In-distribution it doesn't, so the interesting test is adversarial inputs.

### Adversarial: does it help where the prompt is untuned?

To test whether reflection has *latent* value, `eval/golden_adversarial.jsonl` holds 10 harder
cases the tuned prompt is more likely to miss: multi-company news roundups, similar-name traps
(`Halcyon Bank` vs `Halcyon Logistics`), a real breach buried among unrelated funding numbers,
low-severity CVEs that tempt exaggeration, and a competitor's breach sitting next to the
prospect's own CVE (`python -m eval.compare_agent golden_adversarial.jsonl`).

| metric | plain | agent |
|---|---|---|
| no-hallucination rate | 0.6 | 0.8 |
| has_signal accuracy | 1.0 | 0.9 |
| judge faithfulness avg | 4.6 | 4.4 |

The aggregates say "north star up, secondary metrics down," but the **per-case trace is the
honest view** — with only 10 cases and two independently-drafted arms, the aggregates mix loop
effects with generation noise. What actually happened:

- **Reflection worked (as designed).** On the multi-company roundup, the plain draft pulled a
  *different* company's breach into the prospect's brief. The critic caught it and the revision
  removed it — a real dirty→clean fix. This is the failure class the loop targets, and it landed.
- **Reflection backfired.** On the "buried signal" case, the prospect *had* a real, in-context
  breach — but surrounded by unrelated funding noise, the critic **false-positived**, flagged the
  true claim as unsupported, and the loop deleted the real signal (has_signal flipped, faithfulness
  5→3). An over-eager self-critic can erase truth.
- **Two other aggregate swings were noise** — they occurred with zero revisions, so they reflect
  variance between independently generated drafts, not the loop.

The real lesson is sharper than "agents help": **a reflection loop is only as good as its critic's
precision.** A high-recall / low-precision critic buys hallucination fixes at the cost of erasing
real signal. Two follow-ups fall out of this directly: (1) raise critic precision so it stops
flagging in-context claims in noisy multi-company text; (2) fix the ablation confound by having
both arms share the agent's first draft, isolating the loop's true effect. (See `DECISIONS.md`.)

## Design decisions
See `DECISIONS.md` for scope choices and *why* (target market, coverage model, sources, hero insight).

## Roadmap
See `Cyber-Deal-Engine-Roadmap.md`/`.docx` and `Cyber-Deal-Engine-Build-Guide.md`.
