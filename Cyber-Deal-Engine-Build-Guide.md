# Cyber Deal Engine — Step-by-Step Build Guide

A hands-on companion to the roadmap. Follow the steps in order. Every step has a **Do**, a **Code/command**, and a **Checkpoint** so you always know whether it worked before moving on. Concepts you're learning are flagged with 🎓 so you can name the skill in interviews later.

> Baseline assumed: you can write basic Python and use a terminal. Budget ~15–20 hrs/week. Total: 12 weeks.

---

## Phase 0 — Before you write any code (½ day)

### Step 0.1 — Accounts & keys
**Do:** create accounts and grab API keys.

- OpenAI (GPT-4o) — https://platform.openai.com
- Anthropic (Claude) — https://console.anthropic.com
- (Later) Google AI Studio (Gemini), and a small open model via Groq or Together — for eval comparison
- LangSmith (free tier) for tracing — https://smith.langchain.com
- GitHub account + a new private repo `cyber-deal-engine`

**Checkpoint:** you have `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` saved somewhere safe (not in code).

### Step 0.2 — Decide your scope (write it down)
**Do:** pick ONE vertical and 20–30 target companies. Narrow beats broad.

- Example: *Indian mid-market SaaS & fintech firms* (they have real breach exposure + DPDP compliance pressure).
- List the companies in a plain file `data/target_companies.csv` with columns: `company_name, domain, sector, notes`.

**Checkpoint:** `target_companies.csv` exists with ~25 rows.

🎓 *Skill: product scoping — narrowing the problem is itself a PM signal.*

### Step 0.3 — Understand the coverage model (read before you build)
A common confusion: "does the 20–30 companies mean the product only ever works for 20–30 companies?" No. Keep three ideas separate.

- **What a "company" is here.** A company is an account a sales rep is trying to *sell to* — a prospect in their pipeline. Reps don't care about all companies on Earth, only the 50–300 in their book. So scoping to specific companies isn't a limitation; it mirrors how sales actually works.
- **Why 20–30 during the build.** That is *your* sample dataset for developing and evaluating the pipeline. You can't ingest data for thousands of companies or write a 50-case golden set covering all of them while still learning the stack. The 20–30 is a sandbox for you; it expands later and does not cap what the finished product covers.
- **How coverage works in production.** Two modes, and the best product uses both:
  - *Watchlist (proactive push):* each **customer** defines their own target accounts. The system monitors those continuously and pushes a brief before meetings or when a breach signal fires. Bounded per customer → controllable cost and quality. This is the core "just-in-time before the meeting" value.
  - *On-demand (reactive):* a rep types **any** company name and the agent fetches live signals and generates a brief on the spot. Covers the long tail — the new prospect nobody was watching yet.

**Strategy: build watchlist-first, add on-demand later.** Watchlist mode is cheaper, more reliable, and — critically for your career goal — far easier to *evaluate*, because you know the accounts in advance and can build a clean golden dataset. On-demand is more impressive but harder: unpredictable data quality, higher hallucination risk, live-fetch latency and cost. Ship the bounded version, prove quality with numbers, then open it up.

> The list is defined **by each customer's pipeline**, not hardcoded by you. Your 20–30 is only the sandbox you learn in.

🎓 *Skill: coverage/scope design + build sequencing — exactly the kind of design reasoning an AI-PM interviewer probes. Capture your choice in DECISIONS.md.*

### Step 0.4 — Locked scope decisions (this build)

| Dimension | Decision | Why |
|---|---|---|
| **Target market** | Indian mid-market SaaS & fintech — but **architecture stays geo-agnostic** (company list is config) | Thin competition vs. saturated US tools, less signal noise, DPDP gives a datable urgency hook, matches your India TAM/SAM/SOM. Expanding to US tech later is a config change + a growth story, not a rebuild. |
| **Coverage mode** | **Watchlist-first** (Weeks 4–9), then add **on-demand** (Week 10) | Watchlist is cheaper, more reliable, and easy to evaluate cleanly. On-demand is added once quality is proven; it gets its own hallucination-guard eval cases since live data can't be pre-vetted. |
| **Signal sources** | **Layer, don't big-bang.** CVE/NVD + news → CERT-In → financial/funding → *social (stretch)* | "Full" is the end-state, built incrementally so a stuck source never blocks progress. Social is deprioritised: X API is paid/restrictive and LinkedIn is locked down (cost, reliability, legal friction). |
| **Hero insight** | **Breach & vulnerability = hero; compliance (DPDP) = strong #2; tech-stack = minimal** | The hero must be datable, urgent, and tied to what a cyber vendor sells — breach/vuln wins all three and is cleanest to evaluate. Compliance amplifies it and pairs with the India choice. Tech-stack is inference-heavy → highest hallucination risk → keep light early. |

> These are starting commitments, not a cage. Change them if the data tells you to — but log *why* in `DECISIONS.md`.

---

## Phase 1 — A thin vertical slice (Weeks 1–3)

**Goal:** a deployed thing that turns a company blurb into a structured sales brief. No RAG, no agents yet. Prove you can ship.

### Step 1.1 — Environment & repo (Week 1, day 1)
**Do:** set up a clean Python project.

```bash
mkdir cyber-deal-engine && cd cyber-deal-engine
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -U openai anthropic python-dotenv pydantic
git init && echo ".venv/" > .gitignore && echo ".env" >> .gitignore
```

Create `.env`:
```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

**Checkpoint:** `python -c "import openai, anthropic; print('ok')"` prints `ok`.

### Step 1.2 — Your first LLM call
**Do:** create `src/llm.py` — a thin wrapper so you can swap models later.

```python
import os
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv()

client = OpenAI()  # reads OPENAI_API_KEY

def complete(prompt: str, model: str = "gpt-4o", system: str = "") -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system or "You are a concise assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content
```

Test it:
```bash
python -c "from src.llm import complete; print(complete('Say hi in 3 words'))"
```

**Checkpoint:** you get a 3-word reply.

🎓 *Skill: LLM API fundamentals; abstracting the model boundary early.*

### Step 1.3 — Force structured output (the important part)
**Do:** define the brief as a schema with Pydantic, and make the model return valid JSON. Unstructured text is useless downstream.

Create `src/schema.py`:
```python
from pydantic import BaseModel, Field
from typing import List

class Brief(BaseModel):
    company: str
    key_points: List[str] = Field(..., min_length=3, max_length=3,
        description="3 sharp, security-relevant facts a rep can use")
    opener: str = Field(..., description="One strong opening line for the meeting")
    objection_questions: List[str] = Field(..., min_length=3, max_length=3,
        description="3 likely buyer objections framed as questions")
```

Create `src/brief.py`:
```python
import json
from openai import OpenAI
from src.schema import Brief

client = OpenAI()
SYSTEM = (
  "You are a cybersecurity sales intelligence engine. "
  "Given context about a company, produce a pre-meeting brief. "
  "Only use facts present in the context. If unknown, say so — never invent breaches."
)

def generate_brief(company: str, context: str) -> Brief:
    resp = client.chat.completions.parse(   # structured outputs
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Company: {company}\n\nContext:\n{context}"},
        ],
        response_format=Brief,
    )
    return resp.choices[0].message.parsed
```

Test with a hardcoded blurb:
```bash
python -c "from src.brief import generate_brief; \
print(generate_brief('Acme Fintech', 'Acme had a data leak in 2025 exposing 40k records; uses AWS; SOC2 in progress.').model_dump_json(indent=2))"
```

**Checkpoint:** you get valid JSON with exactly 3 key points, an opener, and 3 questions.

🎓 *Skill: structured outputs + guardrails (the "never invent breaches" line is your first hallucination guardrail).*

### Step 1.4 — Handle failure gracefully (Week 2)
**Do:** wrap the call so refusals, timeouts, and bad JSON don't crash the app.

```python
def safe_generate(company, context, retries=2):
    for i in range(retries + 1):
        try:
            return generate_brief(company, context)
        except Exception as e:
            if i == retries:
                return {"error": str(e), "company": company}
```

**Checkpoint:** passing garbage context returns an error object, not a stack trace.

🎓 *Skill: failure-mode handling — a first-class section of an AI-native PRD.*

### Step 1.5 — Deploy a minimal demo (Week 3)
**Do:** wrap it in a tiny web UI and deploy. Simplest path: Streamlit + Streamlit Community Cloud (free), or FastAPI on Render.

```bash
pip install streamlit
```
`app.py`:
```python
import streamlit as st
from src.brief import safe_generate

st.title("Cyber Deal Engine")
company = st.text_input("Company")
context = st.text_area("What you know (paste anything)")
if st.button("Generate brief") and company:
    st.json(safe_generate(company, context))
```
```bash
streamlit run app.py        # test locally, then push to GitHub + deploy on share.streamlit.io
```

**Checkpoint:** a public URL where anyone can generate a brief. Commit + write your first `DECISIONS.md` entry (why GPT-4o, why Streamlit, why this vertical).

🎓 *Skill: shipping a working prototype — the single biggest portfolio differentiator.*

**End of Phase 1:** deployed demo + repo + DECISIONS.md. You can already demo this in an interview.

---

## Phase 2 — Real data + RAG (Weeks 4–6)

**Goal:** replace the pasted blurb with live, retrieved signals grounded in real sources.

### Step 2.1 — Ingest signals (Week 4)
**Do:** pull recent signals for your target companies and store them. Start with 2–3 sources.

Recommended free-ish sources:
- **CVE / NVD** — official vuln feed: https://nvd.nist.gov/developers (JSON API)
- **CERT-In advisories** — India-specific: https://www.cert-in.org.in
- **News** — NewsAPI free tier, or GDELT (free), keyed on company name + "breach/hack/ransomware/data leak"

Install + data model:
```bash
pip install requests sqlalchemy
```
`src/store.py` (SQLite to start — zero setup):
```python
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

Base = declarative_base()
engine = create_engine("sqlite:///signals.db")
Session = sessionmaker(bind=engine)

class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True)
    company = Column(String, index=True)
    source = Column(String)       # nvd | cert-in | news
    title = Column(String)
    body = Column(Text)
    url = Column(String)
    published = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)
```

Write one ingester per source (a function that hits the API, maps fields onto `Signal`, dedupes by `url`, and inserts). Run them on a schedule later; for now run manually.

**Checkpoint:** `signals.db` has real rows for your target companies. Print a count per company.

🎓 *Skill: data pipelines, API integration, normalisation, dedup.*

### Step 2.2 — Embed & index (Week 5)
**Do:** chunk signal text, embed it, store vectors for retrieval.

```bash
pip install langchain langchain-openai langchain-community langchain-text-splitters chromadb
```
`src/index.py`:
```python
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from src.store import Session, Signal

def build_index(persist_dir="chroma_db"):
    rows = Session().query(Signal).all()
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    docs = []
    for r in rows:
        for chunk in splitter.split_text(r.body or r.title):
            docs.append(Document(
                page_content=chunk,
                metadata={"company": r.company, "source": r.source, "url": r.url},
            ))
    return Chroma.from_documents(docs, OpenAIEmbeddings(model="text-embedding-3-small"),
                                 persist_directory=persist_dir)
```

**Checkpoint:** query the store for a company and eyeball whether retrieved chunks are relevant.
```python
db = build_index()
for d in db.similarity_search("Acme Fintech breach", k=3, filter={"company": "Acme Fintech"}):
    print(d.metadata["source"], d.page_content[:120])
```

🎓 *Skill: RAG core — chunking strategy, embeddings, vector search, metadata filtering.*

### Step 2.3 — Grounded brief (Week 6)
**Do:** retrieve per company, feed the retrieved chunks as context, and require citations.

`src/rag_brief.py`:
```python
from src.index import build_index
from src.brief import generate_brief

db = build_index()

def grounded_brief(company: str, k: int = 6):
    hits = db.similarity_search(company, k=k, filter={"company": company})
    context = "\n\n".join(f"[{h.metadata['source']}] {h.page_content}\n(source: {h.metadata['url']})"
                          for h in hits)
    if not context:
        return {"company": company, "note": "No signals found — do not fabricate."}
    return generate_brief(company, context)
```

**Checkpoint:** briefs now reflect real retrieved signals and reference source URLs. Compare a company with signals vs. one without (the second should refuse to invent).

🎓 *Skill: grounding + citation — how you reduce hallucination and make outputs trustworthy.*

**End of Phase 2:** the product runs on live data. Add a `DECISIONS.md` entry on chunk size, embedding model, and Chroma-vs-pgvector.

---

## Phase 3 — Agents + evaluation (Weeks 7–9)  ★ the part that gets you hired

**Goal:** an agent that assembles briefs autonomously, and a real evaluation harness that proves quality with numbers. Protect this phase above all others.

### Step 3.1 — Turn the pipeline into an agent (Week 7)
**Do:** give the model tools (retrieve signals, look up a company, fetch latest CVEs) and let it decide which to call. Use LangGraph's prebuilt ReAct agent.

```bash
pip install -U langgraph langchain-anthropic
```
`src/agent.py`:
```python
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from src.index import build_index

db = build_index()

@tool
def search_signals(company: str) -> str:
    """Retrieve recent security signals for a company from the knowledge store."""
    hits = db.similarity_search(company, k=6, filter={"company": company})
    if not hits:
        return "NO_SIGNALS"
    return "\n\n".join(f"[{h.metadata['source']}] {h.page_content} (src: {h.metadata['url']})"
                       for h in hits)

SYSTEM = ("You build cybersecurity pre-meeting briefs. Use search_signals to gather facts. "
          "Never invent breaches. Output 3 key points, 1 opener, 3 objection questions.")

agent = create_react_agent("openai:gpt-4o", tools=[search_signals], prompt=SYSTEM)

def run_agent(company: str):
    result = agent.invoke({"messages": [("user", f"Prepare a brief for {company}.")]})
    return result["messages"][-1].content
```

**Checkpoint:** `run_agent("Acme Fintech")` calls the tool (visible in LangSmith traces) and returns a brief. Turn on tracing:
```bash
export LANGSMITH_TRACING=true LANGSMITH_API_KEY=...
```

🎓 *Skill: agents & orchestration, tool use — the 2026 frontier skill.*

### Step 3.2 — Build a golden dataset (Week 8, first half)
**Do:** hand-craft ~50 evaluation cases. This is tedious and it is exactly what almost no PM candidate has done.

Create `eval/golden.jsonl`, one case per line:
```json
{"company": "Acme Fintech", "context": "2025 breach, 40k records, AWS, SOC2 WIP",
 "must_include": ["breach", "SOC2"], "must_not": ["ISO 27001 certified"],
 "expected_opener_theme": "recent breach urgency"}
```

Cover: companies with signals, companies without (should refuse), noisy/ambiguous signals, and near-duplicate companies. Include hard negatives so you can catch hallucination.

**Checkpoint:** 50 lines, each with `must_include` / `must_not` assertions.

🎓 *Skill: evaluation dataset design — the foundation of the whole discipline.*

### Step 3.3 — The eval harness (Week 8, second half)
**Do:** score every case two ways — cheap deterministic checks + an LLM-as-judge for quality — and with RAGAS for RAG-specific metrics.

```bash
pip install ragas datasets
```
`eval/run_eval.py` (core loop, simplified):
```python
import json
from src.agent import run_agent
from src.llm import complete

def load(): return [json.loads(l) for l in open("eval/golden.jsonl")]

def deterministic(case, output):
    out = output.lower()
    inc = all(k.lower() in out for k in case.get("must_include", []))
    exc = all(k.lower() not in out for k in case.get("must_not", []))
    return {"include_pass": inc, "no_hallucination": exc}

JUDGE = ("Score this sales brief 1-5 on: faithfulness (only uses given facts), "
         "relevance, and actionability. Return JSON: {faithfulness, relevance, actionability}.")

def judge(case, output):
    return complete(f"Facts:\n{case.get('context','')}\n\nBrief:\n{output}\n\n{JUDGE}",
                    model="gpt-4o")

def main():
    rows = []
    for c in load():
        out = run_agent(c["company"])
        rows.append({**deterministic(c, out), "judge": judge(c, out), "company": c["company"]})
    json.dump(rows, open("eval/results.json", "w"), indent=2)
    passed = sum(r["no_hallucination"] for r in rows)
    print(f"No-hallucination rate: {passed}/{len(rows)}")

if __name__ == "__main__":
    main()
```

For RAGAS metrics (faithfulness, answer/context relevancy) on the retrieval step, follow the RAGAS LangGraph integration: convert messages with `convert_to_ragas_messages`, then score. Keep RAGAS for the RAG layer and your LLM-judge for the brief quality.

**Checkpoint:** `python eval/run_eval.py` prints a no-hallucination rate and writes `results.json`. This number is now your product's north star.

🎓 *Skill: LLM evaluation — golden dataset + LLM-as-judge + RAGAS. This is your headline interview asset.*

### Step 3.4 — Model comparison + cost (Week 9)
**Do:** run the same eval across models and record cost per brief.

- Parameterise `run_agent(company, model)` to accept `openai:gpt-4o`, `anthropic:claude-...`, `google:gemini-...`, and one small open model (via Groq/Together).
- Log token usage per run; multiply by each model's per-token price → **cost per brief**.
- Build a tiny dashboard: a Streamlit page or even a committed `eval/dashboard.md` table updated weekly, showing scores + cost + regressions over time.

**Checkpoint:** a table like:

| Model | No-halluc. | Judge avg | Cost/brief | p50 latency |
|---|---|---|---|---|
| gpt-4o | 48/50 | 4.3 | $0.011 | 3.1s |
| claude | 49/50 | 4.4 | $0.014 | 3.6s |
| gemini-flash | 45/50 | 4.0 | $0.002 | 2.2s |
| open (8B) | 39/50 | 3.4 | $0.001 | 1.8s |

🎓 *Skill: cost-latency modelling + model selection on tradeoffs — reads as "thinks like an owner."*

**End of Phase 3:** a published eval dashboard with regressions over time. This is the strongest single thing in your portfolio.

---

## Phase 4 — Delivery + job-ready artifacts (Weeks 10–12)

### Step 4.1 — Push delivery (Week 10)
**Do:** deliver the brief where the rep already is — a Slack (or Telegram) bot — instead of a portal.

```bash
pip install slack_bolt
```
Minimal Slack app: a slash command `/brief <company>` that calls `run_agent` and posts the brief. Later, trigger automatically from calendar events (a scheduled job that reads tomorrow's meetings and DMs briefs the night before).

**Checkpoint:** typing `/brief Acme Fintech` in Slack returns a formatted brief.

🎓 *Skill: product packaging & distribution — matches the ERRC "eliminate UI barriers" move from your Phase-1 plan.*

### Step 4.2 — The AI-native PRD (Week 11)
**Do:** write `PRD.md`. A normal PRD plus these AI-specific sections (this is what impresses senior AI leaders):

1. Problem, users, requirements, metrics *(standard)*
2. **Model-choice rationale** — your Step 3.4 table + the decision and why
3. **Eval criteria** — what "good" means in numbers (your no-hallucination + judge thresholds)
4. **Failure modes** — hallucinated breach, empty retrieval, stale signal, model refusal — each with *detection* and *response*
5. **Cost model** — cost per brief and how it stays viable at scale
6. **Guardrails** — the "never invent breaches" rule and how you enforce/verify it

**Checkpoint:** `PRD.md` committed with all six sections.

🎓 *Skill: AI-native PRD writing — the highest-value written artifact.*

### Step 4.3 — Package for hiring (Week 12)
**Do:** make everything reachable from one link.

- Polish `README.md`: what it does, architecture diagram, live demo URL, the eval dashboard, link to PRD + DECISIONS.
- Finalise `DECISIONS.md` (why each tech/architecture choice — reasoning, not just code).
- Record a 2–3 min Loom demo: problem → live brief → eval numbers → tradeoffs.
- Write a short case study (can reuse for portfolio site + LinkedIn).
- Start applying + book mock AI-PM interviews.

**Checkpoint:** one portfolio URL from which a hiring manager can reach the demo, the eval dashboard, the PRD, and your reasoning.

---

## Suggested repo structure

```
cyber-deal-engine/
├── src/
│   ├── llm.py          # model wrapper
│   ├── schema.py       # Brief pydantic model
│   ├── brief.py        # structured generation
│   ├── store.py        # signal DB
│   ├── index.py        # embeddings + vector store
│   ├── rag_brief.py    # grounded generation
│   └── agent.py        # LangGraph agent + tools
├── ingest/             # one script per source (nvd, cert-in, news)
├── eval/
│   ├── golden.jsonl    # 50-case golden dataset
│   ├── run_eval.py     # eval harness
│   └── dashboard.md    # weekly scores + cost + regressions
├── app.py              # Streamlit demo
├── slack_app.py        # delivery bot
├── PRD.md
├── DECISIONS.md
└── README.md
```

## Verification checkpoints (don't advance until green)

- **Phase 1:** public URL generates a valid 3+1+3 brief; refuses to invent facts.
- **Phase 2:** briefs cite real retrieved sources; empty-signal company refuses gracefully.
- **Phase 3:** `run_eval.py` prints a no-hallucination rate; multi-model cost table exists.
- **Phase 4:** Slack `/brief` works; PRD has all six AI sections; one portfolio link ties it together.

## Common pitfalls

- **Skipping evals to "add features."** The evals *are* the feature that gets you hired. Build them.
- **Chunk size too big/small.** 600–1000 chars with overlap is a sane start; tune using retrieval hit-rate.
- **Trusting the demo, not the numbers.** A brief that "looks good" on 3 companies can hallucinate on the 4th. Only the golden set tells the truth.
- **Building for 200 companies.** Stay at 20–30. Depth of measurement > breadth of coverage.
- **Committing secrets.** Keep keys in `.env`; confirm `.gitignore` before your first push.

---

*Work the phases in order, keep the evaluation harness as the spine, and log every decision as you go. By Week 12 you'll have a deployed AI product with measured quality — the exact evidence a ₹50 LPA / €150k AI PM is hired to produce.*

