"""Signal storage — the raw material a brief is built from.

Phase 2 turns Cyber Deal Engine from "paste-in context" into "ingest real signals,
store them, retrieve per company". This module is the storage half: a tiny SQLAlchemy
layer over SQLite. Ingesters write Signals here; Phase 2 retrieval and the brief UI read
them back per company.

Why SQLite: zero-setup, file-based, good enough for a bounded watchlist. The Signal model
is storage-agnostic, so swapping to Postgres later is a URL change, not a rewrite.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import String, Text, DateTime, create_engine, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

# Default: a SQLite file at repo root (ignored by .gitignore so raw signals never get
# committed). Override with SIGNALS_DB_URL to point at Postgres in production — no code change.
DB_URL = os.getenv("SIGNALS_DB_URL", "sqlite:///signals.db")


class Base(DeclarativeBase):
    pass


class Signal(Base):
    """One security-relevant item about one company, from one source."""
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(200), index=True)
    source: Mapped[str] = mapped_column(String(50))          # e.g. "nvd", "gdelt"
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, default="")
    # url is the dedup key: the same article/CVE should never be stored twice.
    url: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    published: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def as_context_line(self) -> str:
        """One-line rendering the brief generator can drop straight into context."""
        when = self.published.date().isoformat() if self.published else "date unknown"
        head = f"[{self.source} | {when}] {self.title}"
        return f"{head}\n{self.body}".strip() if self.body else head


_engine = create_engine(DB_URL)
Base.metadata.create_all(_engine)


def add_signal(company: str, source: str, title: str, url: str,
               body: str = "", published: Optional[datetime] = None) -> bool:
    """Insert a signal. Returns True if stored, False if it was a duplicate url.

    Dedup by url is deliberate: ingesters are meant to be re-run (cron/on-demand), so
    they'll keep re-seeing the same items. Silent skip keeps runs idempotent."""
    if not url:
        return False
    with Session(_engine) as s:
        exists = s.scalar(select(Signal.id).where(Signal.url == url))
        if exists:
            return False
        s.add(Signal(company=company, source=source, title=title,
                     url=url, body=body, published=published))
        s.commit()
        return True


def get_signals(company: str, limit: int = 50) -> List[Signal]:
    """Most recent signals for a company (newest first), for retrieval / brief context."""
    with Session(_engine) as s:
        rows = s.scalars(
            select(Signal)
            .where(Signal.company == company)
            .order_by(Signal.published.is_(None), Signal.published.desc(),
                      Signal.ingested_at.desc())
            .limit(limit)
        ).all()
        return list(rows)


def build_context(company: str, limit: int = 15) -> str:
    """Assemble stored signals into a context string for generate_brief()."""
    return "\n\n".join(sig.as_context_line() for sig in get_signals(company, limit))


def counts_by_company() -> dict[str, int]:
    """Quick health check: how many signals we hold per company."""
    with Session(_engine) as s:
        rows = s.execute(
            select(Signal.company, func.count(Signal.id)).group_by(Signal.company)
        ).all()
        return {company: n for company, n in rows}
