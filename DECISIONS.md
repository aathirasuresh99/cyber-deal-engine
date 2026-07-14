# DECISIONS.md — Cyber Deal Engine

A running log of *why* each significant choice was made. Reasoning matters more than the choice itself — this is the file hiring managers read to see how you think. Add an entry every time you make a real decision.

Format: `## [YYYY-MM-DD] Decision title` → **Decision**, **Context**, **Alternatives considered**, **Why**, **Revisit if**.

---

## [2026-07] Scope: target market — Indian mid-market SaaS/fintech, geo-agnostic architecture
**Decision:** Focus the initial sandbox on Indian mid-market SaaS & fintech companies, while keeping the architecture geo-agnostic (the tracked-company list is configuration, not hardcoded logic).

**Context:** Need a bounded, learnable universe for a 3-month solo build that also produces clean evaluation data.

**Alternatives considered:** Global/US tech; Indian BFSI/enterprise; single geo-agnostic sector (e.g. healthcare).

**Why:**
- Thin competition — US tech intelligence is saturated (ZoomInfo, Apollo, Owler, Gong); Indian mid-market tooling is sparse, giving a clearer wedge.
- Lower signal noise — a small, knowable set keeps retrieval precision and eval scores tractable; "US tech" floods the pipeline with low-relevance items.
- Evaluation tractability — ~25 firms → clean ground truth and an easy 50-case golden set; large universes are hard to sample and full of name-collision/disambiguation pain.
- Consistency + urgency hook — matches the existing India TAM/SAM/SOM and the DPDP Act provides a concrete, datable compliance trigger.

**Revisit if:** the pipeline + evals are proven and stable → expand to US/global as a config change and a growth narrative.

---

## [2026-07] Coverage model — watchlist-first, on-demand later
**Decision:** Build watchlist (proactive, per-customer account monitoring) fully first; add on-demand (any-company live brief) as a later extension.

**Context:** Product must eventually serve both a customer's known pipeline and long-tail prospects.

**Alternatives considered:** On-demand only; both simultaneously from day one.

**Why:** Watchlist is cheaper, more reliable, and easy to evaluate because accounts are known in advance. On-demand can't pre-vet live data, so it carries higher hallucination and latency/cost risk — it gets added only after quality is proven, with its own dedicated eval cases.

**Revisit if:** watchlist eval numbers are solid (e.g. no-hallucination rate ≥ 95% on the golden set).

---

## [2026-07] Signal sources — layered, not big-bang
**Decision:** Ingest sources in order of difficulty: CVE/NVD + news → CERT-In → financial/funding → social (stretch). "Full coverage" is the end-state, reached incrementally.

**Context:** Full multi-source ingestion is the goal, but doing it all at once risks a stuck integration blocking the whole build.

**Alternatives considered:** Lean-only (CVE + news); full multi-source from the start.

**Why:** Incremental layering means no single source is a critical-path blocker. Social is explicitly deprioritised — X's API is now paid/restrictive and LinkedIn is heavily locked down, creating cost, reliability, and legal friction disproportionate to its early value.

**Revisit if:** a reliable, compliant social-signal source becomes available at acceptable cost.

---

## [2026-07] Hero insight — breach/vulnerability first, compliance second
**Decision:** Each brief leads with breach & vulnerability signals; compliance (DPDP) triggers are the strong secondary; tech-stack/risk-posture kept minimal early.

**Context:** A brief needs one clear "so what" that a cyber sales rep can open a meeting with.

**Alternatives considered:** Compliance-led; tech-stack-led; all three blended equally.

**Why:** The hero must be datable, urgent, and directly tied to what a cyber vendor sells — breach/vuln wins on all three and is the cleanest to evaluate for faithfulness. Compliance amplifies urgency and pairs naturally with the India focus. Tech-stack inference is soft and hallucination-prone, so it stays light until evals are strong.

**Revisit if:** eval faithfulness is high and users ask for deeper posture/tech-stack context.

---

## [2026-07] Architecture: target market is config, not code
**Decision:** The target geography/segment lives in a single `MarketProfile` config object (`src/config.py`), selected by one switch (`ACTIVE_MARKET`). No product logic (schema, brief generation, retrieval, ingestion) hardcodes a country. `ACTIVE_MARKET = INDIA_MIDMARKET`.

**Context:** We committed to Indian mid-market SaaS/fintech but want expansion to be cheap and low-risk.

**Alternatives considered:** Hardcode India-specific rules (DPDP, RBI) directly in prompts and ingesters; branch on country with `if`-statements.

**Why:** Market-specific detail (compliance frameworks, breach keywords) is *data*, not behaviour. Building for a new market becomes adding a `MarketProfile` and flipping one switch — verified: the same `build_system()` produces a DPDP-flavoured prompt for India and a HIPAA/CCPA one for US tech. Keeps the India focus while making "we scaled to a new geography" a config change plus a growth story, not a rewrite.

**Revisit if:** a market needs genuinely different *logic* (not just different reference data) — then introduce per-profile strategy hooks rather than branching.

---

## [2026-07] Phase 2 signal sources — GDELT for news, NVD for CVEs, both keyless
**Decision:** First two ingesters are NVD 2.0 (CVEs) and GDELT DOC 2.0 (news), both free and requiring no API key. Storage is SQLite via SQLAlchemy, with the DB URL overridable by `SIGNALS_DB_URL`.

**Context:** Phase 2 turns the product from paste-in context to real ingested signals. Need a first, reliable source layer that doesn't block on account/key friction.

**Alternatives considered:** NewsAPI (needs a key, free tier caps to recent articles); paid news/breach feeds; Postgres from day one.

**Why:**
- Keyless sources mean the pipeline runs end-to-end with zero setup — no waiting on a NewsAPI account, consistent with "no single source is a critical-path blocker."
- Honesty guardrail: NVD is a vulnerability *catalogue*, not a breach feed — a keyword hit means "a CVE mentions this term," not "this company was breached." Ingesters store that truthfully; the news layer carries breach *events*. This protects the never-fabricate rule downstream.
- Geo-agnostic: the news ingester is driven by `ACTIVE_MARKET.breach_keywords`, not hardcoded terms. Point it at a different profile and it searches that market.
- SQLite is zero-setup for a bounded watchlist; the `SIGNALS_DB_URL` env override makes the move to Postgres a config change, not a rewrite.

**Revisit if:** GDELT coverage of Indian mid-market names proves thin → add NewsAPI as a second news ingester (key in `.env`, store/runner unchanged), or add CERT-In per the layered-sources plan.

---

## [2026-07] Eval-driven prompt fix — no-signal speculation
**Decision:** Tightened the generator's no-signal rules so that when `has_signal=false`, every field (key points, opener, objection questions) must be fully generic and must not draw inferences from unrelated context (funding rounds, new offices, product launches).

**Context:** First eval run scored no-hallucination rate 1.0 and has_signal accuracy 1.0, but judge faithfulness averaged only 4.3/5. The gap was concentrated in three no-signal/vague cases (GlideDocs 2, MarketBloom 3, TideBank 3): the model correctly flagged no-signal, but its discovery questions speculated about security budget, compliance readiness, and breach implications the context never supported.

**Alternatives considered:** Leave it (not a hard fabrication); add a deterministic check for speculation (hard to define precisely); lower temperature.

**Why:** The failure was a soft-faithfulness issue the LLM judge is designed to catch, and the root cause was a prompt that only constrained `key_points`, not the objection questions. One targeted prompt edit was the cheapest, most direct fix.

**Result:** Re-run scored faithfulness 5.0/5 (up from 4.3); no-hallucination rate held at 1.0. Baseline preserved in eval/results_baseline.json for the before/after.

**Revisit if:** later cases show speculation creeping back, or a real signal case gets over-constrained into blandness — then move some of this into few-shot examples rather than rules.

---

## [2026-07] Production model — gpt-4o-mini over gpt-4o (eval-driven)
**Decision:** Switch DEFAULT_MODEL from gpt-4o to gpt-4o-mini for brief generation.

**Context:** Ran the full golden set through both models with the same deterministic checks and a fixed judge (gpt-4o, so faithfulness is on one scale). gpt-4o-mini matched gpt-4o on the hard guardrails — no-hallucination rate 1.0 and has_signal accuracy 1.0 — while costing ~17x less per brief ($0.00019 vs $0.00329).

**Alternatives considered:** Stay on gpt-4o (safer-sounding, no evidence it's actually better here); jump to a frontier model (higher cost, no eval justification yet).

**Why:** The guardrails that matter for this product (never fabricate a breach/CVE/number) held identically on mini. Faithfulness was within run-to-run noise between the two, so there is no quality justification for paying 17x more. Cost matters at scale (watchlist re-runs briefs continuously).

**Nuance / what I learned:** Single-pass faithfulness is noisy (gpt-4o scored 4.6 and 5.0 on different passes at temperature 0.2). So the comparison harness now runs 3 passes/model and reports mean ± stdev; the model decision rests on the stable guardrail metrics plus a faithfulness range, not one lucky draw.

**Revisit if:** faithfulness stdev turns out large once multi-pass numbers are in, a harder/expanded golden set exposes a quality gap, or a cheaper/stronger model ships. The judge should also move to a different provider (Anthropic) to remove same-family grading bias.

---

## [2026-07] Eval hardening — test bugs vs. model failures
**Decision:** When the expanded golden set (28 cases) produced two no_forbidden failures, treat them by root cause rather than blindly "fixing the model": corrected the over-strict forbidden lists (test bug) and kept the legitimate guard, and made the harness persist each brief's text so failures are debuggable.

**Context:** no-signal-acquisition and misattributed-cve failed the deterministic no_forbidden check, yet both had has_signal_correct=true, judge faithfulness=5, and zero unsupported claims — the judge considered them perfect.

**Diagnosis:**
- Benign no-signal cases (acquisition, ISO cert, exec hire, empty) forbade generic security *words* ("breach", "ransomware", "vulnerability"). But a generic discovery question ("how would you respond to a breach?") is faithful no-signal behavior by our own judge's definition. The test was punishing correct output -> forbidden lists now contain only specific fabricated facts (other-company names, specific numbers, specific CVE ids), never generic vocabulary. The no_fabricated_cve guard already catches invented CVE ids independently.
- misattributed-cve (a CVE belonging to a different company, "Larkspur", vs prospect "Larkfield") kept its strict forbidden list — surfacing an unrelated company's CVE is a real risk, not generic vocabulary.

**Also:** run_eval.py now stores the generated brief (key_points/opener/objection_questions) in results.json, so a failing case can be inspected without a re-run.

**Why it matters:** Distinguishing a mis-specified test from a genuine model regression is the core discipline of running an eval. Relaxing a check to hide a real failure would be gaming the metric; relaxing a check that measures the wrong thing is correcting the instrument. The difference is documented here on purpose.

**Revisit if:** the persisted brief text shows misattributed-cve is dismissing the CVE correctly (then it's a false positive too, and the guard needs to distinguish "cites to dismiss" from "asserts as fact").

---

## [2026-07] Define "signal" precisely — weaknesses only, not posture
**Decision:** A "signal" is an actionable security WEAKNESS/exposure (breach, incident, disclosed CVE/vulnerability, regulatory fine). Positive security-posture news (ISO 27001 / SOC 2 certifications, security awards) and general business news (funding, launches, hires, acquisitions) are explicitly NOT signals. Encoded in both the schema (has_signal description) and the generator prompt.

**Context:** The expanded eval flagged a has_signal mismatch on no-signal-cert (SafeHarbor "achieved ISO 27001"): the model called it has_signal=true, the golden label said false. Root cause was our own ambiguous definition ("real, relevant signals") — a cert is real and security-relevant, so the model wasn't clearly wrong.

**Why weaknesses only:** The product hands a rep an opening. A breach/CVE/fine is an opening; a certification is the opposite (the prospect is already investing, harder to sell). Counting posture/business news as signal would flood the pipeline with false positives and erode the no-hallucination/precision north star, and produce briefs with no hook.

**Revisit if:** a market wants "any security-relevant event" (e.g. competitive-intel use cases) — then has_signal could become a multi-class label (weakness / posture / none) rather than a boolean.

## [2026-07] misattributed-cve — moved from deterministic guard to judge
**Decision:** Removed the forbidden-substring guard (["Larkspur", the CVE id]) from the misattributed-cve case; the test now rests on has_signal_correct (must be false) plus the LLM judge.

**Context:** With the brief text persisted, we could see the model handled the trap correctly: it set has_signal=false and explicitly stated the CVE belongs to "a separate company, Larkspur Analytics." The no_forbidden check fired only because it's a blind substring match — it can't tell "cites Larkspur to dismiss it" (correct) from "asserts Larkspur's CVE as the prospect's" (misattribution).

**Why:** Misattribution is a semantic judgment, not a string presence. Forcing it into a deterministic check produced a false positive on correct behavior. Coverage is retained: true misattribution would flip has_signal to true (caught by has_signal_correct) and tank faithfulness (caught by the judge).

**Note (soft, not fixed):** the model did spin a mild "third-party integration risk" angle off the unrelated CVE. The judge rated it faithful (it was clearly hedged), but a future judge-prompt refinement could penalize manufacturing a hook from an unrelated company's issue.

---

## [2026-07] Independent (Claude) judge — cross-check result + judge of record
**Decision:** Adopt Claude (claude-sonnet-5) as the judge of record for integrity reporting, while keeping gpt-4o as the default so the harness runs for anyone without an Anthropic key. Run the Claude judge for any number that will be quoted externally.

**Context:** Ran the identical 28 briefs (generated by gpt-4o-mini) through both an OpenAI judge and a different-provider Anthropic judge.
- Guardrails identical across judges: no-hallucination 1.0, has_signal accuracy 1.0.
- Soft faithfulness: OpenAI judge 4.79/5 vs Claude judge 4.46/5. Claude is systematically stricter (~0.3 lower) and marked 10/28 below 5.

**Key finding:** On misattributed-cve, the OpenAI judge scored 5/5 but Claude scored 2/5 — Claude caught that the brief's opener pitched a CVE belonging to a *different* company (Larkspur) as a risk to the prospect (Larkfield). The has_signal flag was correctly false and deterministic checks passed, so only a semantic judge could catch it — and the same-family OpenAI judge missed it. This is direct evidence of same-family leniency, i.e. why an independent judge matters.

**Confirmed model weakness (now evidence-backed):** when context contains another company's CVE, the generator sometimes manufactures a sales hook from it. Fix candidate: a prompt rule that an unrelated company's vulnerability must be explicitly excluded from the opener and key points, not spun into third-party risk. Deferred as the next generation improvement.

**Revisit if:** the OpenAI/Claude faithfulness gap widens on future runs (would argue for retiring the OpenAI judge entirely), or a third provider is added to triangulate.

## [2026-07] Misattribution guardrail (prompt rule 2a)
The independent Claude judge caught the one weakness the same-family (OpenAI) judge missed:
on `misattributed-cve`, the brief pitched Larkspur Analytics' CVE to prospect Larkfield
(OpenAI faithfulness 5/5, Claude 2/5). Added prompt rule 2a to src/brief.py: a breach/CVE/
incident belongs to a company only if the context names that same company; a different
company's event (even a similar name) is not a signal and must not be reframed as third-party
risk unless the context explicitly ties it to the prospect. Verify on next eval run.

## [2026-07] Phase 4: reflection agent (self-critique loop)
Added src/critic.py (runtime faithfulness critic: deterministic fabricated-CVE check + LLM
faithfulness pass returning unsupported_claims) and src/agent.py (draft -> critique -> revise,
bounded by max_revisions, returns a full trace). The critic applies the same "faithful" standard
the Phase 3 eval measures, so the agent is held at runtime to exactly what we grade offline —
the payoff of building the eval first. Loop is crash-safe (returns AgentResult with .error) like
safe_generate. Control flow verified in sandbox with mocked generate/critique (clean-first-try,
revise-then-clean with feedback carried, budget-exhausted, graceful fail, deterministic CVE flag).
Next: eval ablation comparing plain generation vs reflective on the 28-case golden set.

## [2026-07] Phase 4 ablation: reflection did NOT beat a tuned prompt (in-distribution)
Ran plain vs. reflective on the 28-case golden set, Claude judge. Result: no-hallucination
1.0 vs 1.0, has_signal 1.0 vs 1.0, faithfulness 4.89 vs 4.86 (flat, within temp noise).
0 hallucinations fixed — after Phase 3 prompt hardening there were none left. The agent
revised 3 cases (cve-clear, vague-incident, phishing-news), all for SOFT over-reach the critic
flags but the judge scores 5/5 anyway (e.g. "posing a significant risk of data breaches").
Finding: the critic is stricter than the judge on inference; the reflection loop only pays off
when the base generator actually slips, which it doesn't in-distribution. Decision: keep the
agent as an available mode but DEFAULT to plain generation (cheaper, equal quality here).
Reflection's value is latent for adversarial/out-of-distribution inputs. Next candidate: an
adversarial eval slice to test that hypothesis rather than assume it.

## [2026-07] Aligned critic and judge on "risk-framing vs asserted-fact"
The Phase 4 ablation surfaced a disagreement: the runtime critic flagged soft phrases like
"a disclosed SQL-injection CVE puts customer data at risk" as unsupported, but the judge scored
those briefs 5/5. Decided the judge was right — stating the RISK a disclosed weakness implies is
reasonable interpretation, not fabrication. Updated both _CRITIC_SYSTEM (src/critic.py) and
_JUDGE_SYSTEM (eval/judge.py) to share one boundary: risk framing is allowed; asserting an event
HAPPENED (breach/exfiltration) when only a vulnerability was disclosed, inventing a fact/number/
date/CVE, or misattributing another company's event, is unsupported. This stops the agent from
making pointless "faithful->faithful" rewrites in-distribution.

## [2026-07] Adversarial eval slice (test reflection's latent value)
Added eval/golden_adversarial.jsonl (10 cases): multi-company roundups, similar-name traps,
signal buried in funding noise, low-severity-CVE exaggeration bait, competitor breach beside the
prospect's own CVE, rumor/number bait. compare_agent.py now takes a golden filename arg and
writes agent_comparison_<stem>.json. Hypothesis under test: reflection's "fixed by reflection"
count should rise on this slice if its value is real where the prompt is untuned. Run pending.

## [2026-07] Adversarial ablation result: reflection helps AND harms — critic precision is the gate
Ran plain vs. agent on the 10-case adversarial slice (Claude judge). Aggregates: no-hallucination
0.6->0.8, has_signal 1.0->0.9, faithfulness 4.6->4.4. Per-case truth (more reliable than
aggregates at n=10):
- WIN: adv-multi-company-noise — plain leaked RivalBank/CloudNine facts into Vertex Pay's brief;
  critic caught all 3, revision removed them (dirty->clean). Reflection did its target job.
- HARM: adv-buried-signal — Quill Health's breach IS in context but buried in funding noise; the
  critic false-positived, flagged the true supported claim across all 3 attempts, and the loop
  deleted the real signal (has_signal True->False, faithfulness 5->3). An over-eager critic erased
  truth. This is the key finding.
- NOISE: adv-two-cves-one-other (clean flip) and adv-similar-name (faith drop) both at rev=0 —
  variance between the two independently drafted arms, not loop effects.
Conclusion: a reflection loop is only as good as its critic's PRECISION. High recall + low
precision trades hallucination fixes for erased signal. Two follow-ups:
  (1) Raise critic precision — stop flagging claims that ARE in the context when the context names
      multiple companies (verify presence before flagging).
  (2) Fix ablation confound — have both arms share the agent's attempt-0 draft so the comparison
      isolates the loop's effect instead of mixing in generation variance.
Both deferred pending user go-ahead (each needs a live eval run to re-verify).

## [2026-07] Critic precision fix (multi-company false-positive)
Fixed the adv-buried-signal defect: the critic flagged "Quill Health confirmed a data breach"
as unsupported even though it was verbatim in the context, because the context also named
unrelated firms (ApexFin/ZenPay/BrightCRM). Added a PRECISION rule to _CRITIC_SYSTEM: confirm a
fact is genuinely ABSENT before flagging; a brief repeating the prospect's own in-context event is
supported even when other companies are mentioned; only flag when the context lacks the claim or
attributes it to a different company; when unsure, re-read and don't flag what is actually present.
Verify on next adversarial run: adv-buried-signal should stop losing its real signal (has_signal
should stay True, no needless revisions), while adv-multi-company-noise should still be caught.
