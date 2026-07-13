# Cyber Deal Engine

Turns cybersecurity signals into pre-meeting sales briefs for cybersecurity sales reps.
Given a prospect company, it produces 3 key points (breach/vulnerability first), a meeting
opener, and 3 objection questions — grounded in real signals, never fabricated.

> Status: **Week 1 — thin vertical slice.** Paste-in context → structured brief. RAG, agents,
> and evaluation come in later phases (see `Cyber-Deal-Engine-Build-Guide.md`).

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
  llm.py       # model wrapper (swap models here)
  schema.py    # Brief output contract (Pydantic)
  brief.py     # structured generation + hallucination guardrail
app.py         # Streamlit demo
data/          # target_companies.csv (your sandbox watchlist)
```

## Design decisions
See `DECISIONS.md` for scope choices and *why* (target market, coverage model, sources, hero insight).

## Roadmap
See `Cyber-Deal-Engine-Roadmap.md`/`.docx` and `Cyber-Deal-Engine-Build-Guide.md`.
