# Real-time signals — how the engine stays current

A brief is only useful if its signals are fresh. There are two complementary paths, and the
product uses **both**.

## 1. On-demand live fetch (primary, works on any company)

`src/live.py` queries the sources **live** for a company at request time — no pre-ingestion, no
stored DB required. It runs the same precision filter and optional embedding rerank as the stored
path, so a live brief and a watchlist brief behave identically.

- **UI:** the **🔍 Live brief** tab. Type any company (or use a watchlist quick-pick), hit *Fetch
  signals & brief*. Fetched signals render as source-tagged cards; the brief is generated from them.
- **CLI:** `python -m src.live "Infosys"`
- **Sources:** NVD (CVEs) is keyless and always on; news needs `NEWSAPI_KEY`. A missing key or a
  source outage is skipped with a note — the brief degrades to generic discovery, it never invents.

This is what makes the product answer *"brief me on this prospect right now"* — the case the
pre-ingested watchlist can't cover, and the only real-time path that survives on an ephemeral host
(Streamlit Cloud wipes the local DB on restart).

## 2. Scheduled watchlist refresh (for a fixed set of accounts)

`ingest/run_ingest.py` pulls and stores signals for every company in
`data/target_companies.csv`. Run it on a schedule to keep the **📇 Watchlist** tab warm.

```bash
python -m ingest.run_ingest            # refresh all watchlist companies
python -m ingest.run_ingest Razorpay   # refresh one
```

**Local cron (macOS/Linux)** — every morning at 07:00:

```cron
0 7 * * *  cd /path/to/Cyber\ Deal\ Engine && /path/to/.venv/bin/python -m ingest.run_ingest >> ingest.log 2>&1
```

**GitHub Actions** — scheduled workflow, keys from repo secrets:

```yaml
on:
  schedule: [{ cron: "0 7 * * *" }]
jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: python -m ingest.run_ingest
        env:
          NEWSAPI_KEY: ${{ secrets.NEWSAPI_KEY }}
          SIGNALS_DB_URL: ${{ secrets.SIGNALS_DB_URL }}   # point at a persistent Postgres
```

### Persistence caveat (honest)

The default store is a local SQLite file. On an ephemeral host (Streamlit Community Cloud) that
file does **not** survive a restart, so a scheduled refresh there is pointless — which is exactly
why on-demand live fetch is the primary mechanism. To make scheduled refresh durable, set
`SIGNALS_DB_URL` to a hosted Postgres; no code changes are needed (see `src/store.py`).

`src.live.live_context(..., persist=True)` can also seed the store from a live lookup — an easy way
to warm the watchlist with companies a rep actually briefed.
