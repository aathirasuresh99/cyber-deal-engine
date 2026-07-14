# Deploying the demo

The Streamlit demo (`app.py`) is designed to run publicly on **Streamlit Community Cloud** (free,
GitHub-based). This guide is the exact steps.

## What works on a public deploy

- **Paste your own** tab — fully standalone. Needs only `OPENAI_API_KEY`. This is the public demo
  path: paste any news/CVE/notes, get a grounded brief. It also exposes the Phase 4 reflection agent
  via a checkbox (draft → self-critique → revise, with the critique trace shown).
- **Watchlist** tab — reads a local signal database (`signals.db`) that is **git-ignored on
  purpose**, so it ships empty. The tab detects this and points visitors to the Paste tab. (To demo
  it live you'd seed a DB in the deploy environment — not required for the public demo.)

## One-time setup

1. **Push to a public GitHub repo** (Streamlit Cloud reads from GitHub). Confirm `.env` and
   `signals.db` are git-ignored and *not* committed:
   ```bash
   git ls-files | grep -E '(\.env|signals\.db)$'   # should print nothing
   ```

2. **Go to** https://share.streamlit.io → sign in with GitHub → **New app**.

3. **Configure the app:**
   - Repository: `aathirasuresh99/<repo>`
   - Branch: `main`
   - Main file path: `app.py`

4. **Add the secret** (Advanced settings → Secrets, TOML format):
   ```toml
   OPENAI_API_KEY = "sk-..."
   ```
   `python-dotenv` isn't used by Streamlit Cloud — it reads `st.secrets`, which are also exposed as
   environment variables, so `os.getenv("OPENAI_API_KEY")` in `src/llm.py` picks them up. No code
   change needed.

5. **Deploy.** First build installs `requirements.txt` (~1–2 min). You get a public URL like
   `https://cyber-deal-engine.streamlit.app`.

## Notes

- **Never paste the key into code or commit it.** Secrets live only in the Streamlit Cloud dashboard.
  Rotate the key if it's ever exposed.
- **Cost:** each brief is ~$0.0002 on `gpt-4o-mini`; the reflection agent adds up to 2 extra
  generate+critique round-trips when toggled on. A public demo is cheap but not free — consider a
  spend cap on the OpenAI key.
- **Reproducing locally:** `streamlit run app.py` with `OPENAI_API_KEY` in `.env`.
- The reflection agent needs `src/agent.py` and `src/critic.py` (already in the repo) — no extra
  dependency beyond `requirements.txt`.
