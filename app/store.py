"""Persistent, change-only history of the collected teams.

Two tables:

* ``board_updates`` — one row per poll whose data changed (any team on the full
  board), with the board size and how many teams were collected. This gives
  history its time axis even when none of *our* teams moved.
* ``team_snapshots`` — one row per collected team **only when something we track
  changed** (score, images, warnings, score time, or any place). Play time ticks
  every minute for active teams, so it's stored but doesn't trigger a row.

SQLAlchemy Core keeps this portable to Postgres. Schema changes later should
move to Alembic; ``create_all`` only creates missing tables.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (Column, DateTime, Float, Index, Integer, MetaData, String, Table,
                        create_engine, event, func, insert, select)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from .scraper import TeamScore

log = logging.getLogger(__name__)

metadata = MetaData()

board_updates = Table(
    "board_updates", metadata,
    Column("id", Integer, primary_key=True),
    Column("observed_at", DateTime, nullable=False, index=True),  # UTC, stored naive
    Column("board_size", Integer, nullable=False),
    Column("collected", Integer, nullable=False),
)

team_snapshots = Table(
    "team_snapshots", metadata,
    Column("id", Integer, primary_key=True),
    Column("team_number", String(32), nullable=False),
    Column("observed_at", DateTime, nullable=False),  # UTC, stored naive
    Column("team_id", Integer),
    Column("location", String(64), nullable=False, default=""),
    Column("division", String(64), nullable=False, default=""),
    Column("tier", String(64), nullable=False, default=""),
    Column("images", Integer),
    Column("play_time", Integer),
    Column("score_time", Integer),
    Column("ccs_score", Float),
    Column("adjustment", Float),
    Column("total", Float),
    Column("code", String(32), nullable=False, default=""),
    Column("place_overall", Integer, nullable=False),
    Column("place_division", Integer, nullable=False),
    Column("place_state", Integer, nullable=False),
    Column("place_state_division", Integer, nullable=False),
    Index("ix_team_snapshots_team_time", "team_number", "observed_at"),
)

_TEAM_FIELDS = [c.name for c in team_snapshots.columns if c.name not in ("id", "observed_at")]


def change_key(t: TeamScore) -> tuple[Any, ...]:
    """What has to differ for a team to get a new snapshot row (not play_time)."""
    return (t.ccs_score, t.total, t.adjustment, t.images, t.code, t.score_time,
            t.place_overall, t.place_division, t.place_state, t.place_state_division,
            t.location, t.division, t.tier)


def _to_db(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


def _from_db(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC)


def _row_to_team(row: Any) -> TeamScore:
    m = row._mapping
    return TeamScore(**{f: m[f] for f in _TEAM_FIELDS})


@dataclass(frozen=True)
class Snapshot:
    observed_at: datetime
    team: TeamScore


@dataclass
class Restored:
    latest: dict[str, Snapshot]     # most recent snapshot per team
    previous: dict[str, Snapshot]   # the one before it, where there is one
    board_size: int = 0
    data_as_of: datetime | None = None


class SnapshotStore:
    def __init__(self, url: str):
        self.url = url
        self.engine = self._make_engine(url)
        # An in-memory database is one shared connection, which isn't safe to use from two
        # threads at once (poller writes vs. request reads). File databases get a connection
        # per thread from the pool, so they don't need this.
        self._lock = threading.Lock() if self.engine.url.database in (None, "", ":memory:") else nullcontext()
        metadata.create_all(self.engine)

    @staticmethod
    def _make_engine(url: str) -> Engine:
        if url in ("sqlite://", "sqlite:///:memory:"):
            # One shared connection, or every thread would get its own empty database.
            return create_engine("sqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url)
        if engine.dialect.name == "sqlite":
            @event.listens_for(engine, "connect")
            def _pragmas(dbapi_conn, _record):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")    # readers don't block the poller's writes
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()
        return engine

    def save(self, observed_at: datetime, board_size: int, collected: int,
             changed: Iterable[TeamScore]) -> int:
        """Record a board change and the snapshots of teams that changed. Returns rows written."""
        at = _to_db(observed_at)
        rows = [{"observed_at": at, **{f: getattr(t, f) for f in _TEAM_FIELDS}} for t in changed]
        with self._lock, self.engine.begin() as conn:
            conn.execute(insert(board_updates).values(observed_at=at, board_size=board_size,
                                                      collected=collected))
            if rows:
                conn.execute(insert(team_snapshots), rows)
        return len(rows)

    def restore(self) -> Restored:
        """The latest two snapshots per team and the last board update, for startup."""
        ranked = select(
            team_snapshots,
            func.row_number().over(partition_by=team_snapshots.c.team_number,
                                   order_by=(team_snapshots.c.observed_at.desc(),
                                             team_snapshots.c.id.desc())).label("rn"),
        ).subquery()
        with self._lock, self.engine.connect() as conn:
            rows = conn.execute(select(ranked).where(ranked.c.rn <= 2)).all()
            last = conn.execute(select(board_updates)
                                .order_by(board_updates.c.observed_at.desc(), board_updates.c.id.desc())
                                .limit(1)).first()
        out = Restored(latest={}, previous={})
        for row in rows:
            snap = Snapshot(_from_db(row.observed_at), _row_to_team(row))
            (out.latest if row.rn == 1 else out.previous)[snap.team.team_number] = snap
        if last is not None:
            out.board_size = last.board_size
            out.data_as_of = _from_db(last.observed_at)
        return out

    def history(self, team_number: str, limit: int = 1000) -> list[Snapshot]:
        """A team's snapshots, oldest first (the most recent ``limit`` of them)."""
        with self._lock, self.engine.connect() as conn:
            rows = conn.execute(select(team_snapshots)
                                .where(team_snapshots.c.team_number == team_number)
                                .order_by(team_snapshots.c.observed_at.desc(), team_snapshots.c.id.desc())
                                .limit(limit)).all()
        return [Snapshot(_from_db(r.observed_at), _row_to_team(r)) for r in reversed(rows)]

    def counts(self) -> dict[str, int]:
        with self._lock, self.engine.connect() as conn:
            return {
                "board_updates": conn.scalar(select(func.count()).select_from(board_updates)),
                "team_snapshots": conn.scalar(select(func.count()).select_from(team_snapshots)),
            }

    def close(self) -> None:
        self.engine.dispose()
