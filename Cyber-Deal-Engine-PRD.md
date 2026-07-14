# Cyber Deal Engine — Product Requirements Document

> An *AI-native* PRD: it specifies not just what the product does, but the model behind it,
> how quality is measured in numbers, and how it fails safely. Sections 5–7 are the parts a
> generic PRD skips and an AI PM is hired to own. Reasoning lives in `DECISIONS.md`; this
> document is the spec that reasoning produced.

---

## 1. Problem & users

Cybersecurity sales reps walk into prospect meetings without knowing the one thing that would
open the conversation: has this company just had a breach, disclosed a vulnerability, or tripped a
compliance trigger? That intelligence exists — in CVE catalogues, news, and regulatory feeds — but
it is scattered, noisy, and full of name collisions. Reps either skip the research or, worse,
improvise a hook that turns out to be wrong (an unrelated company's breach, a CVE that isn't
theirs). A wrong hook is worse than none: it burns credibility in the first thirty seconds.

**Primary user:** a cybersecurity sales rep (AE/SDR) preparing for a first meeting with a named
prospect. Initial market is Indian mid-market SaaS/fintech (see `DECISIONS.md` — thin competition,
low signal noise, DPDP compliance hook, tractable to evaluate), but the architecture is
geo-agnostic: the market is a config object, not code.

**Job to be done:** "Before I meet <company>, give me a defensible reason to open the conversation —
grounded in something that actually happened, never made up."

## 2. What the product produces

For a given prospect the engine emits a structured brief:

- **3 key points**, breach/vulnerability signal first, compliance (DPDP) second.
- **1 meeting opener** the rep can say out loud.
- **3 objection/discovery questions.**

Every claim must trace to an ingested signal. When there is no real signal, the brief says so and
falls back to generic discovery angles rather than inventing an incident. This is the product's one
non-negotiable rule: **never fabricate a breach, CVE, date, or number.**

## 3. How it works (system shape)

```
sources ─► ingest ─► store ─► retrieve ─► generate ─► [critique ─► revise]* ─► brief
 NVD CVE    per-co    SQLite    per-co      LLM         reflection agent (optional)
 news       dedupe              + noise     structured
                               filter       output
```

- **Ingest** (`ingest/`): NVD 2.0 for CVEs and a news source, both keyless first; layered
  additional sources later. NVD is treated honestly as a *vulnerability catalogue*, not a breach
  feed — a keyword hit means "a CVE mentions this term," not "this company was breached."
- **Store** (`src/store.py`): SQLite via SQLAlchemy, dedup by URL, `SIGNALS_DB_URL`-overridable so
  the move to Postgres is a config change.
- **Retrieve** (`src/retrieve.py`): per-company context assembly with NVD name-collision noise
  filtering. (v0 is keyword retrieval; embeddings/reranking is the next upgrade.)
- **Generate** (`src/brief.py`): structured Pydantic output against a hardened prompt.
- **Reflection agent** (`src/agent.py`, optional): draft → critique → revise loop, bounded, with an
  observable trace. Off by default (see §5, §7).

## 4. Requirements

**Functional**
- Generate a structured brief (schema-validated) for any prospect from supplied or stored context.
- Correctly detect signal vs. no-signal and degrade to generic discovery on no-signal.
- Watchlist mode (brief from stored ingested signals) and paste-your-own mode (brief from arbitrary
  pasted text).
- Never emit a CVE id, number, date, or company-specific incident absent from the context.

**Non-functional**
- Cost per brief low enough to re-run a watchlist continuously (target: sub-cent — currently
  ~$0.0002).
- Crash-safe generation: a model/parse failure returns a structured error, never a fabricated brief.
- Reproducible evaluation: every quality claim backed by a re-runnable harness writing to
  `results.json`.

## 5. Model choice — rationale

The production default is **`gpt-4o-mini`**, chosen on evidence, not reputation.

| dimension | decision |
|---|---|
| **Quality** | On the golden set, mini matched gpt-4o on the hard guardrails (no-hallucination 1.0, has_signal accuracy 1.0). Faithfulness was equal within run-to-run noise — mini actually scored *more stable* across passes (4.9 ± 0.0 vs 4.67 ± 0.31). |
| **Cost** | ~$0.0002/brief vs ~$0.0033 for gpt-4o — **~17× cheaper.** Matters because watchlist mode re-runs briefs continuously. |
| **Latency** | Single generation call; mini is faster. The optional reflection loop adds up to `max_revisions` extra generate+critique round-trips, so it is off by default. |
| **Vendor risk** | Provider abstraction in `src/llm.py` (OpenAI generate + lazy Anthropic client). The judge already runs cross-provider (Claude grading OpenAI output), proving the seams work. Switching generation providers is a wrapper change, not a rewrite. |

**Why this is defensible:** the guardrails that matter for this product held identically on the
cheaper model, and there is no faithfulness justification for paying 17× more. The decision rests on
multi-pass numbers (3 passes/model, mean ± sd), not a single lucky draw — because single-pass
faithfulness was demonstrably noisy (gpt-4o scored anywhere from 4.4 to 5.0). See `DECISIONS.md`
"Production model."

**Revisit if:** a harder golden set exposes a quality gap, faithfulness variance turns out large, or
a cheaper/stronger model ships.

## 6. Evaluation — quality in numbers

Quality is measured, not asserted. Two layers run over a hand-built golden dataset:

- **Deterministic checks** (`eval/checks.py`) — free, never flaky: signal-vs-no-signal correctness,
  no forbidden fact echoed (another company's name/number), no invented `CVE-` id.
- **LLM-as-judge** (`eval/judge.py`) — faithfulness, relevance, actionability (1–5) plus a list of
  unsupported claims. Provider-selectable so **Claude grades OpenAI's output** — a genuinely
  independent grader that caught leniency the same-family judge missed.

**North-star metric:** no-hallucination rate (share of briefs breaking none of the fabrication
guards).

| metric | target | current (golden set, Claude judge) |
|---|---|---|
| no-hallucination rate | 1.0 | **1.0** |
| has_signal accuracy | 1.0 | **1.0** |
| judge faithfulness (mean) | ≥ 4.8 | **~4.9** |
| cost / brief | < $0.005 | **~$0.0002** |

**What the eval caught and fixed:** the first run scored a perfect no-hallucination rate but only
4.3/5 faithfulness, localized by the judge to no-signal cases where discovery questions *speculated*
about budget and compliance. One prompt change — forbid inference from unrelated facts across every
field — lifted faithfulness to 5.0 with the guard rate unchanged. The independent Claude judge later
caught a misattribution the OpenAI judge scored 5/5 (pitching another company's CVE to the
prospect), which drove prompt rule 2a. This is the loop the product is built around: *the eval finds
the gap, a targeted change closes it, the number moves.*

## 7. Failure modes — detection & response

Each known failure has a detection mechanism and a defined response. This table is the safety
contract.

| failure mode | detection | response |
|---|---|---|
| **Fabricated CVE id** | Deterministic regex check (`eval/checks.py` + `src/critic.py` `deterministic_flags`) — any `CVE-` id not in context | Hard fail: eval marks dirty; at runtime the critic forces `faithful=False` and the agent revises |
| **Misattribution** (another company's breach/CVE pitched as the prospect's) | Prompt rule 2a constrains generation; independent judge + critic flag it semantically | Excluded from opener/key points; not reframed as third-party risk unless context ties it to the prospect |
| **No-signal speculation** (inventing budget/compliance implications when nothing happened) | Judge faithfulness drop on no-signal cases | Prompt forbids inference from unrelated facts on `has_signal=false`; fall back to generic discovery |
| **Posture-as-signal** (treating ISO/SOC2 certs or funding as a security signal) | `has_signal` mismatch vs golden label | "Signal" defined as weakness/exposure only; certs and business news are explicitly not signals |
| **Critic false-positive** (erasing a *real* buried signal) | Adversarial slice (`golden_adversarial.jsonl`) `has_signal` regressions | Critic precision rule: confirm a fact is genuinely absent before flagging; a prospect's own in-context event stays supported even amid other company names |
| **Generation/parse crash** | `safe_generate` / `AgentResult.error` | Return structured error, never a partial or fabricated brief |

**On the reflection agent specifically:** the ablation showed it does *not* beat a tuned prompt
in-distribution (no hallucinations left to fix after Phase 3 hardening), and that a
low-precision critic can *erase real signal* on adversarial inputs. The honest conclusion — a
reflection loop is only as good as its critic's precision — is why the agent is an available mode,
not the default. See README "The reflection agent — and when it actually helps."

## 8. Scope & roadmap

**In scope now:** watchlist + paste modes, NVD + news ingestion, structured generation with
guardrails, eval harness (deterministic + independent judge), optional reflection agent.

**Deferred, evidence-backed:**
- Embeddings/reranking retrieval (v0 is keyword-only).
- Shared-draft ablation (both arms from the agent's attempt-0 draft) to isolate loop effect from
  generation variance.
- On-demand (any-company) briefs, gated on watchlist no-hallucination rate holding ≥ 0.95.
- Additional sources (CERT-In, financial/funding); social deprioritized on cost/legal friction.
- Packaging: deployed demo URL, eval dashboard, cost model, demo video.

## 9. Open questions

- Does embedding-based retrieval improve faithfulness enough to justify the added infra, or is
  keyword retrieval + noise filtering sufficient at this scale?
- At what golden-set size does the independent judge's ~0.3 strictness gap stabilize enough to quote
  a single faithfulness number externally?
- Should `has_signal` become a multi-class label (weakness / posture / none) for competitive-intel
  use cases, or stay boolean?
