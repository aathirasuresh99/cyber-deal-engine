"""Daily watchlist breach alert — email only NEWLY-appeared signals.

For every company in data/target_companies.csv this fetches live security signals (the same NVD +
NewsAPI live path the app uses), compares each against data/seen_signals.json (URLs we've already
alerted on), and emails ONLY the ones we haven't seen before. The seen-state file is then updated
so the next run won't re-alert on the same signal.

Why a JSON file and not the DB: this is meant to run on a scheduled GitHub Action, whose runner is
ephemeral — the SQLite DB doesn't survive between runs. Persistence instead comes from committing
data/seen_signals.json back to the repo (the workflow does that), which is enough to remember what
we've already sent. No external database required.

Never-fabricate is preserved end to end: the alert only forwards real, cited signals returned by
the live fetch. It generates no brief and asserts nothing the sources didn't say.

Secrets (set as env vars / GitHub repo secrets):
  NEWSAPI_KEY         - for news (NVD is keyless)
  GMAIL_ADDRESS       - the Gmail account that sends the mail
  GMAIL_APP_PASSWORD  - a Gmail App Password (NOT your normal password)
  ALERT_TO            - recipient(s), comma-separated; defaults to GMAIL_ADDRESS

Usage:
  python -m ingest.watchlist_alert            # fetch, dedup, email new signals
  python -m ingest.watchlist_alert --dry-run  # print the email instead of sending (no send, no key needed)
"""
from __future__ import annotations

import csv
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List

from src.config import ACTIVE_MARKET
from src.live import LiveSignal, fetch_live_signals

ROOT = Path(__file__).resolve().parents[1]
WATCHLIST = ROOT / "data" / "target_companies.csv"
SEEN_PATH = ROOT / "data" / "seen_signals.json"

# How far back a signal counts as "recent" for an alert (news + CVE publication window).
RECENT_DAYS = int(os.getenv("ALERT_RECENT_DAYS", "7"))
# Drop seen-state entries older than this so the file doesn't grow forever.
PRUNE_DAYS = int(os.getenv("ALERT_PRUNE_DAYS", "180"))


def _load_watchlist() -> List[str]:
    if not WATCHLIST.exists():
        return []
    with open(WATCHLIST, newline="", encoding="utf-8") as f:
        return [
            row["company_name"].strip()
            for row in csv.DictReader(f)
            if row.get("company_name", "").strip()
        ]


def _load_seen() -> Dict[str, str]:
    """Map of already-alerted signal URL -> ISO timestamp we first saw it."""
    if SEEN_PATH.exists():
        try:
            data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001 - a corrupt state file should not crash the alert
            return {}
    return {}


def _ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc).timestamp()


def _save_seen(seen: Dict[str, str]) -> None:
    """Persist seen-state, pruning entries older than PRUNE_DAYS."""
    cutoff = datetime.now(timezone.utc).timestamp() - PRUNE_DAYS * 86400
    pruned = {url: t for url, t in seen.items() if _ts(t) >= cutoff}
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(pruned, indent=2, sort_keys=True), encoding="utf-8")


def collect_new_signals(seen: Dict[str, str]) -> Dict[str, List[LiveSignal]]:
    """Fetch live signals for every watchlist company; return only URLs not already in `seen`.
    Mutates `seen` to record the new URLs (caller persists it after a successful send)."""
    new_by_company: Dict[str, List[LiveSignal]] = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    for company in _load_watchlist():
        try:
            signals = fetch_live_signals(company, profile=ACTIVE_MARKET, recent_days=RECENT_DAYS)
        except Exception as e:  # noqa: BLE001 - one company failing must not abort the whole run
            print(f"  ! {company}: fetch error: {e}", file=sys.stderr)
            continue
        fresh = [s for s in signals if s.url and s.url not in seen]
        for s in fresh:
            seen[s.url] = now_iso
        if fresh:
            new_by_company[company] = fresh
        print(f"  {company}: {len(signals)} signal(s), {len(fresh)} new")
    return new_by_company


def render_email(new_by_company: Dict[str, List[LiveSignal]]) -> str:
    """Build a simple HTML digest grouped by company."""
    total = sum(len(v) for v in new_by_company.values())
    parts = [
        "<h2>Cyber Deal Engine — new watchlist signals</h2>",
        f"<p>{total} new signal(s) across {len(new_by_company)} company(ies), "
        f"last {RECENT_DAYS} days.</p>",
    ]
    for company, signals in new_by_company.items():
        parts.append(f"<h3>{company}</h3><ul>")
        for s in signals:
            when = s.published.date().isoformat() if s.published else "date unknown"
            parts.append(
                f'<li>[{s.source} &middot; {when}] '
                f'<a href="{s.url}">{s.title}</a></li>'
            )
        parts.append("</ul>")
    parts.append(
        "<hr><p style='color:#888;font-size:12px'>Real, cited signals only — "
        "nothing inferred or invented. Open the Live brief tab to turn any of these into a brief.</p>"
    )
    return "\n".join(parts)


def send_email(html: str, subject: str) -> None:
    """Send the digest over Gmail SMTP (STARTTLS) using an app password."""
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    to_addr = os.getenv("ALERT_TO", user)
    recipients = [a.strip() for a in to_addr.split(",") if a.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, recipients, msg.as_string())


def main() -> int:
    dry_run = "--dry-run" in sys.argv or os.getenv("ALERT_DRY_RUN") == "1"
    seen = _load_seen()
    print(f"Watchlist alert: {len(seen)} previously-seen URL(s); scanning watchlist...")

    new_by_company = collect_new_signals(seen)
    total = sum(len(v) for v in new_by_company.values())

    if total == 0:
        print("No new signals since last run — no email sent.")
        if not dry_run:
            _save_seen(seen)  # still prune old entries (a preview must not mutate state)
        return 0

    html = render_email(new_by_company)
    subject = (
        f"[Cyber Deal Engine] {total} new signal(s) across "
        f"{len(new_by_company)} watchlist company(ies)"
    )

    if dry_run:
        print("DRY RUN — no email sent, seen-state NOT modified. Body below:\n")
        print(html)
        return 0

    send_email(html, subject)
    print(f"Sent: {subject}")
    # Persist only after a successful send, so a send failure retries the same signals next run.
    _save_seen(seen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
