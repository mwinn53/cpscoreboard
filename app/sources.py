"""Where scoreboard responses come from: the live API, a recording of it, or a replay.

* ``LiveSource``    — GETs the scoreboard API.
* ``CaptureSource`` — wraps a live source and saves each *changed* response as
  ``<capture_dir>/<session>/<YYYYmmddTHHMMSSZ>.json.gz``. Dev only.
* ``ReplaySource``  — plays a capture folder back in order, spacing fetches by
  the original gaps divided by ``replay_speed``. Dev only.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .config import ScrapeMode, Settings

log = logging.getLogger(__name__)

CAPTURE_SUFFIX = ".json.gz"
CAPTURE_TS_FORMAT = "%Y%m%dT%H%M%SZ"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Fetch:
    body: bytes
    fetched_at: datetime  # when the data was retrieved (for replay: when it was originally captured)


class Source(ABC):
    description: str = ""

    @abstractmethod
    async def fetch(self) -> Fetch | None:
        """Return the next response, or ``None`` when there's nothing more (replay finished).

        Network and HTTP errors propagate; the poller handles retries.
        """

    def next_delay(self, interval: float) -> float:
        """Seconds to wait before the next fetch."""
        return interval

    async def aclose(self) -> None:
        pass


class LiveSource(Source):
    def __init__(self, url: str, client: httpx.AsyncClient):
        self.url = url
        self.client = client
        self.description = f"live: {url}"

    async def fetch(self) -> Fetch:
        resp = await self.client.get(self.url)
        resp.raise_for_status()
        return Fetch(resp.content, utcnow())


class CaptureSource(Source):
    def __init__(self, inner: Source, directory: Path):
        self.inner = inner
        self.directory = directory
        self.description = f"capture → {directory} ({inner.description})"
        self._last_digest: str | None = None
        self.saved = 0

    async def fetch(self) -> Fetch | None:
        fetch = await self.inner.fetch()
        if fetch is None:
            return None
        digest = hashlib.sha256(fetch.body).hexdigest()
        if digest != self._last_digest:
            path = await asyncio.to_thread(self._save, fetch)
            self._last_digest = digest
            self.saved += 1
            log.info("Captured changed scoreboard to %s", path)
        return fetch

    def _save(self, fetch: Fetch) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (fetch.fetched_at.strftime(CAPTURE_TS_FORMAT) + CAPTURE_SUFFIX)
        tmp = path.with_name(path.name + ".tmp")
        with gzip.open(tmp, "wb") as f:
            f.write(fetch.body)
        tmp.replace(path)
        return path

    def next_delay(self, interval: float) -> float:
        return self.inner.next_delay(interval)

    async def aclose(self) -> None:
        await self.inner.aclose()


def _capture_time(path: Path) -> datetime | None:
    stem = path.name.removesuffix(".gz").removesuffix(".json")
    try:
        return datetime.strptime(stem, CAPTURE_TS_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _read(path: Path) -> bytes:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            return f.read()
    return path.read_bytes()


class ReplaySource(Source):
    def __init__(self, directory: Path, speed: float = 1.0, loop: bool = False, default_gap: float = 60.0):
        if not directory.is_dir():
            raise FileNotFoundError(f"Capture set not found: {directory}")
        files = sorted(p for p in directory.iterdir() if p.name.endswith((".json", ".json.gz")))
        if not files:
            raise FileNotFoundError(f"No .json or .json.gz captures in {directory}")
        self.items = [(p, _capture_time(p)) for p in files]
        self.speed = speed
        self.loop = loop
        self.default_gap = default_gap
        self.description = f"replay: {directory} ({len(files)} captures, {speed:g}x)"
        self._index = 0
        self._delay = 0.0

    @property
    def position(self) -> tuple[int, int]:
        """(captures played, total captures)."""
        return self._index, len(self.items)

    async def fetch(self) -> Fetch | None:
        if self._index >= len(self.items):
            if not self.loop:
                return None
            self._index = 0
        path, ts = self.items[self._index]
        body = await asyncio.to_thread(_read, path)

        gap = self.default_gap
        if self._index + 1 < len(self.items):
            next_ts = self.items[self._index + 1][1]
            if ts and next_ts:
                gap = max((next_ts - ts).total_seconds(), 0.0)
        self._delay = gap / self.speed
        self._index += 1
        return Fetch(body, ts or utcnow())

    def next_delay(self, interval: float) -> float:
        return self._delay


def build_source(settings: Settings, client: httpx.AsyncClient) -> Source:
    if settings.scrape_mode is ScrapeMode.replay:
        return ReplaySource(settings.capture_set_path, settings.replay_speed, settings.replay_loop,
                            default_gap=settings.poll_interval)
    live = LiveSource(settings.scoreboard_url, client)
    if settings.scrape_mode is ScrapeMode.capture:
        session = utcnow().strftime("%Y-%m-%d_%H%M%S")
        return CaptureSource(live, settings.capture_dir / session)
    return live
