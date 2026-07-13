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
