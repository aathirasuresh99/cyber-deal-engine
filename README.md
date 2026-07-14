# Cyber Deal Engine

Turns cybersecurity signals into pre-meeting sales briefs for cybersecurity sales reps.
Given a prospect company, it produces 3 key points (led by the highest-urgency buying trigger), a
meeting opener, and 3 objection questions — grounded in real signals, never fabricated.

A "signal" is any cyber **buying trigger** a rep can open on — breach/incident, disclosed
vulnerability, compliance pressure, peer/industry breach, M&A or fundraising, growth/change,
customer security demand, insurer/board pressure, or a visibility gap (`src/schema.py`). Each
trigger must trace to a real, cited event; broadening what *counts* never loosens the
never-fabricate rule. Works in real time: the **🔍 Live brief** tab fetches signals live for any
company (`src/live.py`), and a scheduled watchlist refresh keeps tracked accounts warm — see
`REALTIME.md`.

**Live demo:** https://cyber-deal-engine.streamlit.app/ — use the *Paste your own* tab (paste any
news/CVE text) and toggle the reflection agent to watch it self-critique. (The *Watchlist* tab
needs a locally ingested signal DB, so it's empty on the public demo by design.)

> Status: **signal pipeline + evaluation harness + reflection agent working.** Ingests real CVE
> (NVD) and news (NewsAPI) signals, stores and retrieves them per company, generates a structured
> brief, scores quality with an automated eval harness (deterministic guardrails + LLM-as-judge),
> and can self-critique and revise its own drafts against that same faithfulness standard.
> Retrieval adds an opt-in embedding reranker on top of the precision filter (`RETRIEVAL_MODE=embedding`).

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
  retrieve.py  # per-company retrieval: precision filter + opt-in embedding rerank
  live.py      # on-demand live fetch (NVD + news) — real-time brief for any company
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

**Current run — re-labelled Phase 5 golden set (33 cases, 28 signal / 5 no-signal):**

| metric | value |
|---|---|
| no-hallucination rate | **1.0** |
| has_signal accuracy | 0.939 |
| judge faithfulness avg | 4.94 / 5 |

The golden set was **re-labelled** for the full buying-trigger taxonomy: three business-event cases
that were "no signal" under the breach/vuln-only rule are now positive (new-office/hiring = growth,
Series B = fundraising, definitive acquisition = M&A), and five new positive cases were added (cloud
migration, SOC 2 customer demand, DPDP deadline, cyber-insurance renewal, peer breach). Posture
(ISO/SOC2 already achieved), a personnel appointment, and a misattributed CVE stay correctly
labelled no-signal. Fabrication guardrails (never invent a CVE/date/number/incident) now scan every
brief field including the Phase 5 ones.

The two `has_signal` misses are both the *softest* triggers — a new office + hiring (growth) and a
Series B raise (fundraising), each with zero security context. The model calls these "no signal,"
erring conservative: it under-detects a soft business trigger rather than fabricating one, so the
no-hallucination rate stays 1.0. That trade (recall on the softest triggers vs. never over-firing on
routine funding/growth news) is a deliberate characteristic, not a defect. A separate run caught a
real prompt gap: on a noisy multi-company case the model pulled an *unrelated* firm's record-quarter
news into the brief as fake "competitive scrutiny" — both the deterministic forbidden-string guard
and the judge flagged it, and a prompt rule (a different company's non-security business news is
never a trigger) fixed it, restoring the rate to 1.0. See `DECISIONS.md` "Phase 5."

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

The first adversarial run exposed both an upside and a real defect, which drove a critic fix. The
table below is *after* that fix:

| metric | plain | agent |
|---|---|---|
| no-hallucination rate | 0.7 | 0.8 |
| has_signal accuracy | 0.9 | 1.0 |
| judge faithfulness avg | 4.89 | 4.2 |

With only 10 cases and two independently-drafted arms, the aggregates mix loop effects with
generation noise, so the **per-case trace is the honest view**:

- **Reflection worked (as designed).** On the multi-company roundup, the plain draft pulled a
  *different* company's breach into the prospect's brief. The critic caught it and the revision
  removed it — a real dirty→clean fix. This is the failure class the loop targets, and it landed.
- **The critic first backfired, then was fixed.** On the "buried signal" case, the prospect *had*
  a real, in-context breach surrounded by unrelated funding noise. In the first run the critic
  **false-positived** — flagged the true claim as unsupported — and the loop deleted the real
  signal (has_signal flipped, faithfulness 5→3). The fix was a *precision* rule: confirm a fact is
  genuinely absent before flagging, and treat the prospect's own in-context event as supported even
  when other companies are named. After it, that case passes on the first try (0 revisions, signal
  preserved) while the multi-company catch still fires — so `has_signal` accuracy went 0.9→1.0 with
  no lost true-positive.
- **The remaining faithfulness gap is a confound, not a regression.** Every case where the two arms
  disagree on faithfulness has `rev=0` — the loop never ran on it — so the gap is variance between
  independently generated drafts. The one case the loop actually revised held faithfulness at 5.

The lesson is sharper than "agents help": **a reflection loop is only as good as its critic's
precision** — a high-recall/low-precision critic trades hallucination fixes for erased signal. And
the faithfulness confound drove the next fix (now implemented): both arms share the agent's
attempt-0 draft (`AgentResult.first_draft`), so a case the loop never revised shows an exactly zero
delta by construction and any non-zero delta is unambiguously the loop — not drafting noise. (Live
re-run pending to refresh the numbers above; see `DECISIONS.md`.)

## Design decisions
See `DECISIONS.md` for scope choices and *why* (target market, coverage model, sources, hero insight).

## Roadmap
See `Cyber-Deal-Engine-Roadmap.md`/`.docx` and `Cyber-Deal-Engine-Build-Guide.md`.
