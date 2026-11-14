"""Season archive: the full raw scoreboard, one file per day.

The public scoreboard is taken down after the season, and the database only keeps
history for the collected teams. So whenever the board changes, the complete API
response (every team, every division) is written to ``<DATA_DIR>/archive/``,
replacing that day's previous file. Each day therefore keeps its *last* board,
which on a competition day is the board as the round closed.

Files use the capture format (``YYYYmmddTHHMMSSZ.json.gz``, UTC), so an archive
folder can be replayed in dev with ``SCRAPE_MODE=replay CAPTURE_SET=<folder>``.
"Day" means the display time zone's calendar day (US Eastern by default).
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .sources import CAPTURE_SUFFIX, CAPTURE_TS_FORMAT

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^\d{8}T\d{6}Z\.json\.gz$")


@dataclass(frozen=True)
class ArchiveFile:
    name: str
    saved_at: datetime  # UTC
    day: date           # local calendar day
    size: int           # bytes, compressed


class Archive:
    def __init__(self, directory: Path, timezone: str = "America/New_York"):
        self.directory = directory
        self.tz = ZoneInfo(timezone)
        self._mutex = threading.Lock()

    def _day(self, when: datetime) -> date:
        return when.astimezone(self.tz).date()

    def files(self) -> list[ArchiveFile]:
        """Newest first."""
        if not self.directory.is_dir():
            return []
        out = []
        for path in self.directory.iterdir():
            if not NAME_RE.match(path.name):
                continue
            saved = datetime.strptime(path.name.removesuffix(CAPTURE_SUFFIX), CAPTURE_TS_FORMAT).replace(tzinfo=UTC)
            out.append(ArchiveFile(path.name, saved, self._day(saved), path.stat().st_size))
        return sorted(out, key=lambda f: f.saved_at, reverse=True)

    def path(self, name: str) -> Path | None:
        """The file for a download, or None (also for anything that isn't an archive name)."""
        if not NAME_RE.match(name):
            return None
        path = self.directory / name
        return path if path.is_file() else None

    def save(self, body: bytes, fetched_at: datetime) -> Path:
        """Write this board as the day's file, replacing any earlier file from the same day."""
        with self._mutex:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / (fetched_at.astimezone(UTC).strftime(CAPTURE_TS_FORMAT) + CAPTURE_SUFFIX)
            tmp = path.with_name(path.name + ".tmp")
            with gzip.open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, path)
            day = self._day(fetched_at)
            for old in self.files():
                if old.day == day and old.name != path.name:
                    (self.directory / old.name).unlink(missing_ok=True)
            return path
