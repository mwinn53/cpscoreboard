"""Round samples for the Analysis tab: one frozen copy of a round's results per division.

A *round sample* is everything the analysis needs, captured once the round's
scoring has gone quiet (app/analysis_sampler.py) or imported from the legacy
season files (app/analysis_legacy.py):

* ``analysis_rounds``: which season, round and division; when sampled; the
  coaches' notes. Season comes from team numbers / image names (``cp19`` = 19);
  the round key from image names (``r1``, ``r2``, ``state``, ``sf``…).
* ``analysis_teams``: every team's final row (score, challenge scores, play time,
  places within the division, and the local grouping: ``ems`` for our teams,
  ``district`` for other district schools).
* ``analysis_images``: every team's per-image results (found, remaining,
  penalties, score, time).
* ``analysis_timeline``: per team and image, the scoreboard's 5-minute score
  history for the round (in-round comparisons).

Samples don't change when the live board does, so reports are reproducible; a
re-sample replaces the rows and bumps ``revision``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import (Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint,
                        delete, insert, select, update)

from .store import SnapshotStore, _from_db, _to_db, metadata

PRELIMINARY, FINAL = "preliminary", "final"
LIVE, LEGACY = "live", "legacy"
EMS, DISTRICT = "ems", "district"

ROUND_LABELS = {"r1": "Round 1", "r2": "Round 2", "r3": "Round 3", "state": "State Round", "st": "State Round",
                "sf": "Semifinal", "semi": "Semifinal", "semis": "Semifinal", "nf": "National Finals",
                "final": "National Finals"}
ROUND_ORDER = {"r1": 1, "r2": 2, "r3": 3, "state": 4, "st": 4, "sf": 5, "semi": 5, "semis": 5, "nf": 6, "final": 6}

analysis_rounds = Table(
    "analysis_rounds", metadata,
    Column("id", Integer, primary_key=True),
    Column("season", Integer, nullable=False),
    Column("round_key", String(32), nullable=False),
    Column("label", String(100), nullable=False),
    Column("division", String(64), nullable=False),
    Column("status", String(16), nullable=False),     # preliminary / final
    Column("source", String(16), nullable=False),     # live / legacy
    Column("sampled_at", DateTime, nullable=False),   # UTC, naive
    Column("revision", Integer, nullable=False, server_default="1"),
    Column("team_count", Integer, nullable=False, server_default="0"),
    Column("images", String(500), nullable=False, server_default=""),  # comma-separated short names
    Column("notes", Text, nullable=False, server_default=""),
    UniqueConstraint("season", "round_key", "division", "status", name="uq_analysis_round"),
)

analysis_teams = Table(
    "analysis_teams", metadata,
    Column("id", Integer, primary_key=True),
    Column("round_id", Integer, ForeignKey("analysis_rounds.id", ondelete="CASCADE"), nullable=False),
    Column("team_number", String(32), nullable=False),
    Column("name", String(100), nullable=False, server_default=""),
    Column("grp", String(16), nullable=False, server_default=""),  # ems / district / ""
    Column("location", String(64), nullable=False, server_default=""),
    Column("tier", String(64), nullable=False, server_default=""),
    Column("images", Integer),
    Column("play_time", Integer),    # seconds
    Column("score_time", Integer),
    Column("ccs_score", Float),
    Column("challenge_1", Float),    # e.g. Cisco
    Column("challenge_2", Float),
    Column("adjustment", Float),
    Column("total", Float),
    Column("code", String(32), nullable=False, server_default=""),
    Column("place_division", Integer),
    Column("place_state_division", Integer),
    Index("ix_analysis_teams_round", "round_id"),
)

analysis_images = Table(
    "analysis_images", metadata,
    Column("id", Integer, primary_key=True),
    Column("round_id", Integer, ForeignKey("analysis_rounds.id", ondelete="CASCADE"), nullable=False),
    Column("team_number", String(32), nullable=False),
    Column("image", String(64), nullable=False),        # short name, e.g. Windows11
    Column("image_full", String(128), nullable=False, server_default=""),
    Column("found", Integer),
    Column("remaining", Integer),
    Column("penalties", Integer),
    Column("score", Float),
    Column("duration", Integer),   # seconds on the image
    Column("code", String(32), nullable=False, server_default=""),
    Index("ix_analysis_images_round", "round_id"),
)

analysis_timeline = Table(
    "analysis_timeline", metadata,
    Column("id", Integer, primary_key=True),
    Column("round_id", Integer, ForeignKey("analysis_rounds.id", ondelete="CASCADE"), nullable=False),
    Column("team_number", String(32), nullable=False),
    Column("image", String(64), nullable=False),
    Column("at", DateTime, nullable=False),
    Column("score", Float, nullable=False),
    Index("ix_analysis_timeline_round", "round_id"),
)

# --- names ---

_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
_SEASON_RE = re.compile(r"^cp([0-9]+|[ivxlc]+)$", re.IGNORECASE)
_ROUND_RE = re.compile(r"^(r\d+|sf|semis?|state|st|nf|final)$", re.IGNORECASE)


def roman(text: str) -> int:
    total, prev = 0, 0
    for ch in reversed(text.lower()):
        v = _ROMAN[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def parse_image_name(full: str) -> tuple[str, int | None, str | None]:
    """"Debian12_cp19_intro_r2_hsms" -> ("Debian12", 19, "r2"); "Win10_cpxii_sf_gsms" -> ("Windows10", 12, "sf")."""
    parts = full.split("_")
    for i, part in enumerate(parts):
        m = _SEASON_RE.match(part)
        if m and i > 0:
            short = "_".join(parts[:i])
            season = int(m.group(1)) if m.group(1).isdigit() else roman(m.group(1))
            rnd = next((p.lower() for p in parts[i + 1:] if _ROUND_RE.match(p)), None)
            break
    else:
        short, season, rnd = full, None, None
    short = re.sub(r"^Win(\d)", r"Windows\1", short)
    return short, season, rnd


def round_identity(image_names: Iterable[str], team_numbers: Iterable[str]) -> tuple[int | None, str | None]:
    """The most common season and round key across a round's images (season falls back to team numbers)."""
    seasons, rounds = Counter(), Counter()
    for full in image_names:
        _, season, rnd = parse_image_name(full)
        if season:
            seasons[season] += 1
        if rnd:
            rounds[rnd] += 1
    if not seasons:
        prefixes = Counter(n.split("-")[0] for n in team_numbers if "-" in n)
        if prefixes and prefixes.most_common(1)[0][0].isdigit():
            seasons[int(prefixes.most_common(1)[0][0])] = 1
    return (seasons.most_common(1)[0][0] if seasons else None,
            rounds.most_common(1)[0][0] if rounds else None)


def default_label(round_key: str) -> str:
    return ROUND_LABELS.get(round_key, round_key.upper())


# --- records ---

@dataclass
class TeamRow:
    team_number: str
    location: str = ""
    tier: str = ""
    name: str = ""
    grp: str = ""
    images: int | None = None
    play_time: int | None = None
    score_time: int | None = None
    ccs_score: float | None = None
    challenge_1: float | None = None
    challenge_2: float | None = None
    adjustment: float | None = None
    total: float | None = None
    code: str = ""
    place_division: int | None = None
    place_state_division: int | None = None

    @property
    def score(self) -> float:
        """The ranked score: the official total when present, else the CCS score."""
        return self.total if self.total is not None else (self.ccs_score or 0.0)


@dataclass
class ImageRow:
    team_number: str
    image: str
    image_full: str = ""
    found: int | None = None
    remaining: int | None = None
    penalties: int | None = None
    score: float | None = None
    duration: int | None = None
    code: str = ""


@dataclass
class Sample:
    """A whole round sample, ready to store."""
    season: int
    round_key: str
    division: str
    status: str
    source: str
    sampled_at: datetime
    teams: list[TeamRow]
    images: list[ImageRow] = field(default_factory=list)
    timeline: list[tuple[str, str, datetime, float]] = field(default_factory=list)  # team, image, at, score
    label: str = ""


@dataclass(frozen=True)
class RoundInfo:
    id: int
    season: int
    round_key: str
    label: str
    division: str
    status: str
    source: str
    sampled_at: datetime
    revision: int
    team_count: int
    images: tuple[str, ...]
    notes: str

    @property
    def order(self) -> tuple[int, int]:
        return self.season, ROUND_ORDER.get(self.round_key, 9)

    @property
    def title(self) -> str:
        return f"CP-{self.season} {self.label}"


def _info(r) -> RoundInfo:
    return RoundInfo(r.id, r.season, r.round_key, r.label, r.division, r.status, r.source, _from_db(r.sampled_at),
                     r.revision, r.team_count, tuple(x for x in r.images.split(",") if x), r.notes)


class AnalysisStore:
    def __init__(self, store: SnapshotStore):
        self.store = store

    def save(self, sample: Sample) -> RoundInfo:
        """Insert or replace a round sample (same season, round, division and status)."""
        images = sorted({i.image for i in sample.images})
        values = {"season": sample.season, "round_key": sample.round_key,
                  "label": sample.label or default_label(sample.round_key), "division": sample.division,
                  "status": sample.status, "source": sample.source, "sampled_at": _to_db(sample.sampled_at),
                  "team_count": len(sample.teams), "images": ",".join(images)}
        r = analysis_rounds.c
        with self.store.lock, self.store.engine.begin() as conn:
            existing = conn.execute(select(analysis_rounds).where(
                r.season == sample.season, r.round_key == sample.round_key, r.division == sample.division,
                r.status == sample.status)).first()
            if existing is None:
                round_id = conn.execute(insert(analysis_rounds).values(**values, revision=1)).inserted_primary_key[0]
            else:
                round_id = existing.id
                values.pop("label")  # keep a coach's rename
                conn.execute(update(analysis_rounds).where(r.id == round_id)
                             .values(**values, revision=existing.revision + 1))
                for t in (analysis_teams, analysis_images, analysis_timeline):
                    conn.execute(delete(t).where(t.c.round_id == round_id))
            if sample.teams:
                conn.execute(insert(analysis_teams), [{"round_id": round_id, **vars(t)} for t in sample.teams])
            if sample.images:
                conn.execute(insert(analysis_images), [{"round_id": round_id, **vars(i)} for i in sample.images])
            if sample.timeline:
                conn.execute(insert(analysis_timeline), [
                    {"round_id": round_id, "team_number": t, "image": img, "at": _to_db(at), "score": s}
                    for t, img, at, s in sample.timeline])
        return self.get(round_id)

    def get(self, round_id: int) -> RoundInfo | None:
        with self.store.lock, self.store.engine.connect() as conn:
            row = conn.execute(select(analysis_rounds).where(analysis_rounds.c.id == round_id)).first()
        return _info(row) if row else None

    def rounds(self, division: str | None = None) -> list[RoundInfo]:
        q = select(analysis_rounds)
        if division:
            q = q.where(analysis_rounds.c.division == division)
        with self.store.lock, self.store.engine.connect() as conn:
            rows = [_info(r) for r in conn.execute(q)]
        return sorted(rows, key=lambda i: (i.order, i.status == FINAL), reverse=True)  # final first

    def divisions(self) -> list[str]:
        with self.store.lock, self.store.engine.connect() as conn:
            return sorted({r[0] for r in conn.execute(select(analysis_rounds.c.division))})

    def find(self, season: int, round_key: str, division: str) -> list[RoundInfo]:
        r = analysis_rounds.c
        with self.store.lock, self.store.engine.connect() as conn:
            return [_info(x) for x in conn.execute(select(analysis_rounds).where(
                r.season == season, r.round_key == round_key, r.division == division))]

    def teams(self, round_id: int) -> list[TeamRow]:
        cols = [c.name for c in analysis_teams.columns if c.name not in ("id", "round_id")]
        with self.store.lock, self.store.engine.connect() as conn:
            rows = conn.execute(select(analysis_teams).where(analysis_teams.c.round_id == round_id)).all()
        return [TeamRow(**{c: getattr(r, c) for c in cols}) for r in rows]

    def images(self, round_id: int) -> list[ImageRow]:
        cols = [c.name for c in analysis_images.columns if c.name not in ("id", "round_id")]
        with self.store.lock, self.store.engine.connect() as conn:
            rows = conn.execute(select(analysis_images).where(analysis_images.c.round_id == round_id)).all()
        return [ImageRow(**{c: getattr(r, c) for c in cols}) for r in rows]

    def timeline(self, round_id: int) -> list[tuple[str, str, datetime, float]]:
        t = analysis_timeline.c
        with self.store.lock, self.store.engine.connect() as conn:
            rows = conn.execute(select(t.team_number, t.image, t.at, t.score).where(t.round_id == round_id)
                                .order_by(t.at)).all()
        return [(r.team_number, r.image, _from_db(r.at), r.score) for r in rows]

    def update_round(self, round_id: int, **values) -> None:
        allowed = {k: v for k, v in values.items() if k in ("label", "notes", "status")}
        if allowed:
            with self.store.lock, self.store.engine.begin() as conn:
                conn.execute(update(analysis_rounds).where(analysis_rounds.c.id == round_id).values(**allowed))

    def delete_round(self, round_id: int) -> None:
        with self.store.lock, self.store.engine.begin() as conn:
            for t in (analysis_teams, analysis_images, analysis_timeline):
                conn.execute(delete(t).where(t.c.round_id == round_id))
            conn.execute(delete(analysis_rounds).where(analysis_rounds.c.id == round_id))


def utcnow() -> datetime:
    return datetime.now(UTC)
