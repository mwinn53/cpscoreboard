"""Background loop: fetch, parse when the data changed, store what changed, notify viewers."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime

from .collection import CollectionFilter
from .events import BoardNotifier
from .scraper import ScoreboardFormatError, TeamScore, parse_scores
from .sources import Source, utcnow
from .store import SnapshotStore, change_key

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TeamChange:
    """How a team moved at its most recent change."""
    at: datetime
    score_delta: float  # points
    place_delta: int    # division places gained (positive = moved up)

    @property
    def visible(self) -> bool:
        return bool(self.score_delta or self.place_delta)


def team_change(before: TeamScore, after: TeamScore, at: datetime) -> TeamChange:
    return TeamChange(at=at, score_delta=round(after.score - before.score, 2),
                      place_delta=before.place_division - after.place_division)


@dataclass
class BoardState:
    teams: list[TeamScore] = field(default_factory=list)  # collected teams only
    by_number: dict[str, TeamScore] = field(default_factory=dict)
    changes: dict[str, TeamChange] = field(default_factory=dict)
    board_size: int = 0                   # teams on the full board before filtering
    data_as_of: datetime | None = None    # time of the fetch that confirmed the current data
    last_changed: datetime | None = None  # wall-clock time the data last changed
    last_error: str | None = None
    polls: int = 0
    changes_seen: int = 0
    finished: bool = False                # replay ran out of captures
    restored: bool = False                # showing data from the database until the first live poll


class Poller:
    MAX_BACKOFF = 600.0

    def __init__(self, source: Source, interval: float, collect: CollectionFilter | None = None,
                 store: SnapshotStore | None = None, notifier: BoardNotifier | None = None):
        self.source = source
        self.interval = interval
        self.collect = collect or CollectionFilter()
        self.store = store
        self.notifier = notifier or BoardNotifier()
        self.state = BoardState()
        self._digest: str | None = None
        self._failures = 0
        self._stored: dict[str, TeamScore] = {}  # last version of each team written to the store
        self._pending_write: asyncio.Future | None = None

    async def drain(self) -> None:
        """Wait for an in-flight database write (call after cancelling run(), before closing the store)."""
        if self._pending_write is not None and not self._pending_write.done():
            with suppress(Exception):
                await self._pending_write

    def _set_teams(self, teams: list[TeamScore]) -> None:
        self.state.teams = teams
        self.state.by_number = {t.team_number: t for t in teams}

    def restore(self) -> None:
        """Load the last known board from the store, so restarts don't start blank."""
        if self.store is None:
            return
        r = self.store.restore()
        self._stored = {n: s.team for n, s in r.latest.items()}
        self.state.changes = {n: team_change(r.previous[n].team, s.team, s.observed_at)
                              for n, s in r.latest.items() if n in r.previous}
        teams = sorted(self.collect.apply([s.team for s in r.latest.values()]),
                       key=lambda t: t.place_overall)
        if teams:
            self._set_teams(teams)
            self.state.board_size = r.board_size
            self.state.data_as_of = r.data_as_of
            self.state.restored = True
            log.info("Restored %d teams from the database (as of %s)", len(teams), r.data_as_of)

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

        changed = [t for t in kept
                   if t.team_number not in self._stored or change_key(self._stored[t.team_number]) != change_key(t)]
        error = None
        if self.store is not None:
            try:
                # Shielded: cancelling the poller (shutdown) must not abandon a write mid-transaction.
                # drain() waits for it before the store is closed.
                self._pending_write = asyncio.ensure_future(
                    asyncio.to_thread(self.store.save, fetch.fetched_at, len(teams), len(kept), changed))
                written = await asyncio.shield(self._pending_write)
                log.debug("Stored %d team snapshots", written)
            except Exception as e:
                log.exception("Failed to store snapshots")
                error = f"database write failed: {e}"
                changed = []  # not stored, so compare against the old versions again next time

        for t in changed:
            before = self._stored.get(t.team_number)
            if before is not None:
                self.state.changes[t.team_number] = team_change(before, t, fetch.fetched_at)
            self._stored[t.team_number] = t

        # On a failed write, leave the digest unset so the next poll retries even if nothing changed.
        self._digest = digest if error is None else None
        self._failures = 0
        self._set_teams(kept)
        self.state.board_size = len(teams)
        self.state.data_as_of = fetch.fetched_at
        self.state.last_changed = utcnow()
        self.state.last_error = error
        self.state.changes_seen += 1
        self.state.restored = False
        log.info("Scoreboard updated: kept %d of %d teams, %d changed", len(kept), len(teams), len(changed))
        await self.notifier.publish()
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
