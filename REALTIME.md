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

## 3. Daily email alert on NEW signals (shipped)

`ingest/watchlist_alert.py` + `.github/workflows/watchlist-alert.yml` run every day, fetch live
signals for every watchlist company, and **email only the signals not seen before** — so you get a
note when a tracked account has a fresh breach/CVE/security-news hit, not a repeat of yesterday's.

State is kept in `data/seen_signals.json` (URLs already emailed). The runner is ephemeral, so the
workflow commits that file back to the repo after each run — that's how "new since last time" works
without a database. Old entries prune after 180 days so the file stays small.

```bash
python -m ingest.watchlist_alert            # fetch, dedup, email new signals
python -m ingest.watchlist_alert --dry-run  # print the digest instead of sending (no key needed)
```

**Repo secrets to set** (Settings → Secrets and variables → Actions):

| secret | what |
|---|---|
| `NEWSAPI_KEY` | news source (NVD is keyless) |
| `GMAIL_ADDRESS` | the Gmail account that sends |
| `GMAIL_APP_PASSWORD` | a Gmail **App Password** (not your login password; needs 2FA on) |
| `ALERT_TO` | recipient(s), comma-separated (defaults to `GMAIL_ADDRESS`) |

Scope note: this alerts once per day on the schedule, not the instant a breach happens — true
push-on-event would need continuous monitoring infra. The digest lists signals; open the **Live
brief** tab to turn any into a full brief.

### Persistence caveat (honest)

The default store is a local SQLite file. On an ephemeral host (Streamlit Community Cloud) that
file does **not** survive a restart, so a scheduled refresh there is pointless — which is exactly
why on-demand live fetch is the primary mechanism. To make scheduled refresh durable, set
`SIGNALS_DB_URL` to a hosted Postgres; no code changes are needed (see `src/store.py`).

`src.live.live_context(..., persist=True)` can also seed the store from a live lookup — an easy way
to warm the watchlist with companies a rep actually briefed.

## 4. Making the hosted Watchlist tab persist (Neon Postgres)

The Watchlist tab is empty on the public demo because SQLite is wiped on restart. Point the store at
a free hosted Postgres and it survives. `src/store.py` already reads `SIGNALS_DB_URL`, so this is
config only — no code change (the Postgres driver `psycopg2-binary` is already in `requirements.txt`).

1. **Create a free Neon Postgres.** Sign up at neon.tech → new project → copy the **connection
   string**. It looks like `postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require`.
   SQLAlchemy wants the `postgresql://` scheme (if Neon shows `postgres://`, just change the prefix).

2. **Give the Streamlit app the URL.** In the app dashboard → *Settings → Secrets*, add:
   ```toml
   SIGNALS_DB_URL = "postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require"
   ```
   The app reads it via `os.getenv`; the tables auto-create on first connect (`Base.metadata.create_all`).

3. **Give the scheduled refresh the same URL.** Add `SIGNALS_DB_URL` as a GitHub repo secret and pass
   it to `run_ingest` (the workflow in section 2 already wires it), so the cron writes into the same
   Postgres the app reads.

4. **Seed it once** so the tab isn't empty on first load — run either locally or from the Action:
   ```bash
   SIGNALS_DB_URL="postgresql://...:...@...neon.tech/...?sslmode=require" \
     python -m ingest.run_ingest
   ```

After that the **📇 Watchlist** tab on the hosted demo shows stored signals, and the daily refresh
keeps them current. Live brief stays the zero-setup path; this just makes the stored path durable too.
