"""Background loop: fetch from the source, parse when the data changed, keep the latest board.

Milestone 3 adds persistence (snapshots in the database) and push updates.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime

from .collection import CollectionFilter
from .scraper import ScoreboardFormatError, TeamScore, parse_scores
from .sources import Source, utcnow

log = logging.getLogger(__name__)


@dataclass
class BoardState:
    teams: list[TeamScore] = field(default_factory=list)  # collected teams only
    by_number: dict[str, TeamScore] = field(default_factory=dict)
    board_size: int = 0                   # teams on the full board before filtering
    data_as_of: datetime | None = None    # time of the fetch that confirmed the current data
    last_changed: datetime | None = None  # wall-clock time the data last changed
    last_error: str | None = None
    polls: int = 0
    changes: int = 0
    finished: bool = False                # replay ran out of captures


class Poller:
    MAX_BACKOFF = 600.0

    def __init__(self, source: Source, interval: float, collect: CollectionFilter | None = None):
        self.source = source
        self.interval = interval
        self.collect = collect or CollectionFilter()
        self.state = BoardState()
        self._digest: str | None = None
        self._failures = 0

    def _fail(self, message: str) -> bool:
        self._failures += 1
        self.state.last_error = message
        return False

    async def poll_once(self) -> bool:
        """Fetch once. Returns True if the board changed."""
        try:
            fetch = await self.source.fetch()
        except Exception as e:  # network, HTTP status, unreadable capture...
            log.warning("Scoreboard fetch failed: %s", e)
            return self._fail(f"fetch failed: {e}")

        if fetch is None:
            self.state.finished = True
            return False

        self.state.polls += 1
        digest = hashlib.sha256(fetch.body).hexdigest()
        if digest == self._digest:
            self._failures = 0
            self.state.last_error = None
            self.state.data_as_of = fetch.fetched_at
            return False

        try:
            teams = parse_scores(fetch.body)
        except ScoreboardFormatError as e:
            log.warning("Unexpected scoreboard response: %s", e)
            return self._fail(str(e))

        kept = self.collect.apply(teams)  # after parse_scores ranked the full board
        if teams and not kept:
            log.warning("Collection filter (%s) matched none of %d teams", self.collect.describe(), len(teams))

        self._digest = digest
        self._failures = 0
        self.state.teams = kept
        self.state.by_number = {t.team_number: t for t in kept}
        self.state.board_size = len(teams)
        self.state.data_as_of = fetch.fetched_at
        self.state.last_changed = utcnow()
        self.state.last_error = None
        self.state.changes += 1
        log.info("Scoreboard updated: kept %d of %d teams", len(kept), len(teams))
        return True

    def next_delay(self) -> float:
        if self._failures:
            return min(self.interval * 2 ** self._failures, self.MAX_BACKOFF)
        return self.source.next_delay(self.interval)

    async def run(self) -> None:
        log.info("Poller started (%s)", self.source.description)
        while True:
            await self.poll_once()
            if self.state.finished:
                log.info("Replay finished; keeping the last board")
                return
            await asyncio.sleep(self.next_delay())
