"""Per-image detail for the watched teams (issue #19).

The public scoreboard's team page reads ``/api/image/scores.php?team=<n>``: one row
per competition image with its score, vulnerabilities found and remaining,
penalties, time on the image and warning codes. The main board only has totals, so
this is the only place per-image progress shows up.

To keep requests and the database small, only watched teams are fetched, every
``DETAIL_INTERVAL`` seconds (5 minutes by default), and only while the team is
playing: a team is fetched when its play time has moved since its last fetch (plus
once more after it stops, which catches the final numbers).

Rows are stored change-only in ``image_snapshots``, like the board: time on the
image ticks constantly, so it's stored but doesn't by itself make a new row.

Sources mirror app/sources.py: live, capture (saves each changed response under
``<session>/images/<team>/``) and replay (serves the newest saved response per
team from ``<capture set>/images/<team>/``, if the set has one).
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Table, insert, select

from .config import ScrapeMode, Settings
from .scraper import parse_hms
from .sources import CAPTURE_SUFFIX, CAPTURE_TS_FORMAT, utcnow
from .store import SnapshotStore, _from_db, _to_db, metadata

log = logging.getLogger(__name__)

image_snapshots = Table(
    "image_snapshots", metadata,
    Column("id", Integer, primary_key=True),
    Column("team_number", String(32), nullable=False),
    Column("observed_at", DateTime, nullable=False),  # UTC, stored naive
    Column("image", String(128), nullable=False),
    Column("duration", Integer),   # seconds on the image
    Column("found", Integer),
    Column("remaining", Integer),
    Column("penalties", Integer),
    Column("code", String(32), nullable=False, default=""),
    Column("ccs_score", Float),
    Index("ix_image_snapshots_team_time", "team_number", "observed_at"),
)


@dataclass(frozen=True)
class ImageScore:
    image: str
    duration: int | None
    found: int | None
    remaining: int | None
    penalties: int | None
    code: str
    ccs_score: float | None

    @property
    def change_key(self) -> tuple[Any, ...]:
        return (self.found, self.remaining, self.penalties, self.code, self.ccs_score)


@dataclass(frozen=True)
class ImageSnapshot:
    observed_at: datetime
    image: ImageScore


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_images(body: bytes) -> list[ImageScore]:
    """The image rows of one team's response, sorted by image name. Raises ValueError if unreadable."""
    try:
        doc = json.loads(body)
    except ValueError as e:
        raise ValueError(f"not JSON: {e}") from e
    rows = doc.get("data") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        raise ValueError("no data list")
    out = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("image"):
            continue
        out.append(ImageScore(image=str(r["image"]), duration=parse_hms(r.get("duration")),
                              found=_int(r.get("found")), remaining=_int(r.get("remaining")),
                              penalties=_int(r.get("penalties")), code=str(r.get("code") or ""),
                              ccs_score=_float(r.get("ccs_score"))))
    return sorted(out, key=lambda i: i.image)


class DetailStore:
    """``image_snapshots`` on the shared database (the table is created with the others)."""

    def __init__(self, store: SnapshotStore):
        self.store = store
        metadata.create_all(store.engine, tables=[image_snapshots])

    def save(self, team: str, at: datetime, images: Iterable[ImageScore]) -> int:
        rows = [{"team_number": team, "observed_at": _to_db(at), "image": i.image, "duration": i.duration,
                 "found": i.found, "remaining": i.remaining, "penalties": i.penalties, "code": i.code,
                 "ccs_score": i.ccs_score} for i in images]
        if rows:
            with self.store.lock, self.store.engine.begin() as conn:
                conn.execute(insert(image_snapshots), rows)
        return len(rows)

    def history(self, team: str, limit: int = 5000) -> list[ImageSnapshot]:
        t = image_snapshots.c
        with self.store.lock, self.store.engine.connect() as conn:
            rows = conn.execute(select(image_snapshots).where(t.team_number == team)
                                .order_by(t.observed_at.desc(), t.id.desc()).limit(limit)).all()
        return [ImageSnapshot(_from_db(r.observed_at),
                              ImageScore(r.image, r.duration, r.found, r.remaining, r.penalties, r.code, r.ccs_score))
                for r in reversed(rows)]

    def latest(self) -> dict[str, dict[str, ImageSnapshot]]:
        """The last stored row per (team, image), to resume change detection after a restart."""
        out: dict[str, dict[str, ImageSnapshot]] = {}
        t = image_snapshots.c
        with self.store.lock, self.store.engine.connect() as conn:
            for r in conn.execute(select(image_snapshots).order_by(t.observed_at, t.id)):
                out.setdefault(r.team_number, {})[r.image] = ImageSnapshot(
                    _from_db(r.observed_at),
                    ImageScore(r.image, r.duration, r.found, r.remaining, r.penalties, r.code, r.ccs_score))
        return out


# --- Sources ---

def detail_url(scoreboard_url: str) -> str:
    """.../api/team/scores.php -> .../api/image/scores.php"""
    return scoreboard_url.replace("/team/scores.php", "/image/scores.php")


class LiveDetail:
    def __init__(self, url: str, client: httpx.AsyncClient):
        self.url, self.client = url, client
        self.description = f"live: {url}"

    async def fetch(self, team: str) -> bytes | None:
        resp = await self.client.get(self.url, params={"team": team})
        resp.raise_for_status()
        return resp.content


class CaptureDetail:
    def __init__(self, inner: LiveDetail, directory: Path):
        self.inner, self.directory = inner, directory
        self.description = f"capture → {directory} ({inner.description})"
        self._digests: dict[str, str] = {}

    async def fetch(self, team: str) -> bytes | None:
        body = await self.inner.fetch(team)
        digest = hashlib.sha256(body or b"").hexdigest()
        if body is not None and self._digests.get(team) != digest:
            self._digests[team] = digest
            await asyncio.to_thread(self._save, team, body)
        return body

    def _save(self, team: str, body: bytes) -> None:
        folder = self.directory / team
        folder.mkdir(parents=True, exist_ok=True)
        with gzip.open(folder / (utcnow().strftime(CAPTURE_TS_FORMAT) + CAPTURE_SUFFIX), "wb") as f:
            f.write(body)


class ReplayDetail:
    def __init__(self, directory: Path):
        self.directory = directory
        self.description = f"replay: {directory}"

    async def fetch(self, team: str) -> bytes | None:
        folder = self.directory / team
        if not folder.is_dir():
            return None
        files = sorted(p for p in folder.iterdir() if p.name.endswith((".json", ".json.gz")))
        if not files:
            return None
        path = files[-1]
        return gzip.decompress(path.read_bytes()) if path.name.endswith(".gz") else path.read_bytes()


def build_detail_source(settings: Settings, client: httpx.AsyncClient, capture_session: Path | None = None):
    if settings.scrape_mode is ScrapeMode.replay:
        folder = settings.capture_set_path / "images"
        return ReplayDetail(folder) if folder.is_dir() else None
    live = LiveDetail(detail_url(settings.scoreboard_url), client)
    if settings.scrape_mode is ScrapeMode.capture and capture_session is not None:
        return CaptureDetail(live, capture_session / "images")
    return live


# --- Poller ---

class DetailPoller:
    """Fetches per-image detail for watched teams that are playing."""

    def __init__(self, source, store: DetailStore | None, interval: float,
                 watched: Callable[[], Iterable[str]], play_time: Callable[[str], int | None]):
        self.source, self.store, self.interval = source, store, interval
        self.watched, self.play_time = watched, play_time
        self.latest: dict[str, tuple[datetime, list[ImageScore]]] = {}  # team -> last fetch
        self._stored: dict[str, dict[str, ImageScore]] = {}
        self._fetched_play_time: dict[str, int | None] = {}

    def restore(self) -> None:
        if self.store is None:
            return
        for team, images in self.store.latest().items():
            self._stored[team] = {name: s.image for name, s in images.items()}
            at = max(s.observed_at for s in images.values())
            self.latest[team] = (at, sorted((s.image for s in images.values()), key=lambda i: i.image))

    def due(self) -> list[str]:
        """Watched teams that are on the board and have played since their last fetch."""
        out = []
        for team in self.watched():
            pt = self.play_time(team)
            if pt is None:  # not on the board
                continue
            if team not in self._fetched_play_time or self._fetched_play_time[team] != pt:
                out.append(team)
        return out

    async def fetch_team(self, team: str) -> int:
        """Fetch one team; returns how many image rows were stored."""
        play_time = self.play_time(team)
        body = await self.source.fetch(team)
        self._fetched_play_time[team] = play_time
        if body is None:
            return 0
        images = parse_images(body)
        if not images:
            return 0
        now = utcnow()
        self.latest[team] = (now, images)
        before = self._stored.get(team, {})
        changed = [i for i in images if i.image not in before or before[i.image].change_key != i.change_key]
        if changed and self.store is not None:
            await asyncio.to_thread(self.store.save, team, now, changed)
        self._stored[team] = {i.image: i for i in images}
        return len(changed)

    async def poll_once(self) -> int:
        stored = 0
        for team in self.due():
            try:
                stored += await self.fetch_team(team)
            except Exception as e:
                log.warning("Image detail for %s failed: %s", team, e)
        return stored

    async def run(self) -> None:
        log.info("Image detail poller started (%s, every %gs)", self.source.description, self.interval)
        await asyncio.sleep(min(self.interval, 30))  # let the board load first
        while True:
            await self.poll_once()
            await asyncio.sleep(self.interval)
