"""Fill each round's live data set a team at a time, as teams finish (Analysis tab).

The poller keeps the full board in memory. For each division chosen in the
settings (Middle School by default), the collector watches every team's **play
time**. Reports are written after the round, so a team is collected only when it's
surely finished: at least ``MIN_PLAY`` (3¾ hours) played and no play for
``DONE_AFTER`` (60 minutes), or idle for ``GIVE_UP_AFTER`` (4 hours) whatever it
played. **Collect all** fetches a division's remaining teams now, finished or not, at
the same throttle and pace. Its per-image results, challenge
scores and 5-minute image history are then fetched from its subpages on the public
scoreboard (two requests: the Cisco scores and total come from the board itself) and saved to the round's data set
(app/analysis_store.py). Teams finish across the whole weekend, so collection is a
trickle rather than one burst at the end, and waiting this long means few teams are
fetched twice.

* **Throttle:** how many teams are fetched at once (``analysis_concurrency``,
  default 1; 0 pauses), with a short pause after each team.
* **Again only when needed:** a team is fetched again only if its score changes
  after it was collected (late corrections, or a new round on the board).
* **Places:** places keep moving while other teams play, so collected teams'
  board fields (places, play time, flags) are refreshed from the board for free.
* **Progress:** per division, teams collected out of those that have played, the
  number waiting, the number still playing and an ETA from the recent pace.

The season comes from the team's image names (``…_cp19_…``). The round does too, unless
the admin sets it on the Analysis page: image names aren't reliable for the round
(CP-19 Round 1 used ``…_cp19_intro_r2_…`` images).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from .analysis_store import DISTRICT, EMS, AnalysisStore, ImageRow, TeamRow, parse_image_name, round_identity
from .board_config import BoardConfig
from .scraper import TeamScore
from .team_detail import _float, chart_url, detail_url, parse_image_chart, parse_images

log = logging.getLogger(__name__)

DIVISIONS_KEY, CONCURRENCY_KEY, ROUND_KEY = "analysis_divisions", "analysis_concurrency", "analysis_round"
DEFAULT_DIVISIONS, DEFAULT_CONCURRENCY, MAX_CONCURRENCY = "Middle School", 1, 6
MIN_PLAY = int(3.75 * 3600)          # seconds played before a team counts as finished
DONE_AFTER = timedelta(minutes=60)   # ...and no play for this long
GIVE_UP_AFTER = timedelta(hours=4)   # or idle this long, whatever it played
TICK = 5                             # seconds between scheduling passes while there's work
IDLE_TICK = 30
PAUSE = 1.0                          # seconds after each team, per worker
RETRY_AFTER = timedelta(minutes=30)  # after a team's fetch failed
REFRESH_EVERY = timedelta(minutes=10)


def score_key(t: TeamScore) -> str:
    """Changes only when the team's score does."""
    return f"{t.ccs_score}|{t.adjustment}|{t.total}"


@dataclass
class DivisionStatus:
    division: str
    played: int = 0          # teams on the board with play time
    collected: int = 0       # collected at their current score
    waiting: int = 0         # done, not collected yet
    playing: int = 0         # still playing
    fetching: int = 0
    round_id: int | None = None   # the data set being filled
    eta_seconds: float | None = None
    forced: bool = False          # Collect all is running

    @property
    def complete(self) -> bool:
        return self.played > 0 and self.collected >= self.played

    @property
    def percent(self) -> int:
        return round(100 * self.collected / self.played) if self.played else 0


class AnalysisCollector:
    def __init__(self, store: AnalysisStore, board: BoardConfig, client: httpx.AsyncClient,
                 full_board: Callable[[], list[TeamScore]], scoreboard_url: Callable[[], str],
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.store, self.board, self.client = store, board, client
        self.full_board, self.scoreboard_url, self.clock = full_board, scoreboard_url, clock
        self.moved: dict[str, tuple[int, datetime]] = {}   # team -> (play time, when it last changed)
        self.failed: dict[str, tuple[str, datetime]] = {}  # team -> (score key, when the fetch failed)
        self.inflight: set[str] = set()
        self.tasks: set[asyncio.Task] = set()
        self.pace: float | None = None                       # seconds per team (moving average)
        self.status: dict[str, DivisionStatus] = {}
        self.forced: set[str] = set()                        # divisions where Collect all is running
        self.last_error = ""
        self._refreshed: datetime | None = None

    # --- settings ---

    def divisions(self) -> list[str]:
        raw = self.board.get_value(DIVISIONS_KEY)
        return [d for d in (raw.split("|") if raw else [DEFAULT_DIVISIONS]) if d]

    def set_divisions(self, divisions: list[str]) -> None:
        self.board.set_value(DIVISIONS_KEY, "|".join(divisions) if divisions else "|")

    def concurrency(self) -> int:
        try:
            return max(0, min(int(self.board.get_value(CONCURRENCY_KEY) or DEFAULT_CONCURRENCY), MAX_CONCURRENCY))
        except ValueError:
            return DEFAULT_CONCURRENCY

    def set_concurrency(self, n: int) -> None:
        self.board.set_value(CONCURRENCY_KEY, str(max(0, min(n, MAX_CONCURRENCY))))

    def round_key(self) -> str:
        """The round being collected, as set by the admin ("" = from the image names)."""
        return self.board.get_value(ROUND_KEY)

    def set_round(self, key: str) -> None:
        self.board.set_value(ROUND_KEY, key)

    def collect_all(self, division: str) -> None:
        """Fetch the division's remaining teams now, finished or not (same throttle and pace)."""
        self.forced.add(division)

    # --- who's done ---

    def observe(self, teams: list[TeamScore]) -> None:
        now = self.clock()
        for t in teams:
            pt = t.play_time or 0
            prev = self.moved.get(t.team_number)
            if prev is None or prev[0] != pt:
                self.moved[t.team_number] = (pt, now)

    def done(self, t: TeamScore) -> bool:
        seen = self.moved.get(t.team_number)
        if not t.play_time or seen is None:
            return False
        idle = self.clock() - seen[1]
        return idle >= GIVE_UP_AFTER or (t.play_time >= MIN_PLAY and idle >= DONE_AFTER)

    def plan(self) -> list[TeamScore]:
        """Update each division's status; return the teams to fetch, in finishing order."""
        teams = self.full_board()
        self.observe(teams)
        now = self.clock()
        pending, status = [], {}
        conc = self.concurrency()
        for division in self.divisions():
            st = DivisionStatus(division)
            collected = self.store.collected(division)
            latest = max(collected.values(), key=lambda v: v[0], default=None)
            st.round_id = latest[0] if latest else None
            for t in teams:
                if t.division != division or not t.play_time:
                    continue
                st.played += 1
                key = score_key(t)
                if collected.get(t.team_number, (None, None))[1] == key:
                    st.collected += 1
                elif t.team_number in self.inflight:
                    st.fetching += 1
                elif not self.done(t) and division not in self.forced:
                    st.playing += 1
                else:
                    st.waiting += 1
                    failed = self.failed.get(t.team_number)
                    if not (failed and failed[0] == key and now - failed[1] < RETRY_AFTER):
                        pending.append(t)
            if division in self.forced and not st.waiting and not st.fetching:
                self.forced.discard(division)   # the pass is done; back to the usual rule
            st.forced = division in self.forced
            left = st.waiting + st.fetching
            if left and conc:
                st.eta_seconds = left * ((self.pace or 4.0) + PAUSE) / conc
            status[division] = st
        self.status = status
        pending.sort(key=lambda t: self.moved[t.team_number][1])
        return pending

    # --- fetching ---

    def _groups(self) -> dict[str, tuple[str, str]]:
        """team -> (name, group) from the watchlist (ours) and the district schools."""
        out = {n: (self.board.schools.get(n, ""), DISTRICT) for n in self.board.aliases}
        for n in self.board.watchlist:
            out[n] = (self.board.schools.get(n, "") or self.board.watch_school, EMS)
        return out

    async def _get(self, url: str, team: str) -> bytes | None:
        for attempt in range(2):
            try:
                resp = await self.client.get(url, params={"team": team}, timeout=30)
                resp.raise_for_status()
                return resp.content
            except httpx.HTTPError as e:
                if attempt:
                    log.info("Analysis fetch %s for %s failed: %s", url, team, e)
                    self.last_error = f"{team}: {e}"
                await asyncio.sleep(2)
        return None

    async def collect(self, t: TeamScore) -> bool:
        """Fetch one team's subpages and save it to its round's data set."""
        started = time.monotonic()
        base = self.scoreboard_url()
        # The board feed carries Cisco Quiz (score_1), Packet Tracer (score_2) and the total, so the team's own
        # row is fetched only when the board row isn't the live one (restored from the database).
        detail = json.dumps({"data": [t.raw]}).encode() if "score_1" in t.raw else await self._get(base, t.team_number)
        images = await self._get(detail_url(base), t.team_number)
        chart = await self._get(chart_url(base), t.team_number)
        now = self.clock()
        if detail is None and images is None:
            self.failed[t.team_number] = (score_key(t), now)
            return False
        extra = {}
        if detail:
            try:
                rows = json.loads(detail).get("data") or [{}]
                extra = rows[0] if isinstance(rows, list) and rows else {}
            except (ValueError, AttributeError):
                pass
        img_rows = []
        if images:
            try:
                img_rows = parse_images(images)
            except ValueError:
                pass
        series = []
        if chart:
            try:
                series = parse_image_chart(chart, now)
            except ValueError:
                pass
        season, round_key = round_identity([i.image for i in img_rows], [t.team_number])
        round_key = self.round_key() or round_key
        if season is None or round_key is None:
            current = self.store.get(self.status[t.division].round_id) if self.status.get(t.division) and \
                self.status[t.division].round_id else None
            if current is None:
                self.failed[t.team_number] = (score_key(t), now)
                self.last_error = f"couldn't tell which round {t.team_number}'s images are from"
                return False
            season, round_key = current.season, current.round_key
        name, grp = self._groups().get(t.team_number, ("", ""))
        team = TeamRow(
            team_number=t.team_number, location=t.location, tier=t.tier, name=name, grp=grp, images=t.images,
            play_time=t.play_time, score_time=t.score_time, ccs_score=t.ccs_score,
            challenge_1=_float(extra.get("score_1")), challenge_2=_float(extra.get("score_2")),
            adjustment=_float(extra.get("adjustment")) if extra.get("adjustment") is not None else t.adjustment,
            total=_float(extra.get("total")) if extra.get("total") is not None else t.total,
            code=t.code, place_division=t.place_division, place_state_division=t.place_state_division)
        rows = []
        for i in img_rows:
            short, _, _ = parse_image_name(i.image)
            rows.append(ImageRow(team_number=t.team_number, image=short, image_full=i.image, found=i.found,
                                 remaining=i.remaining, penalties=i.penalties, score=i.ccs_score,
                                 duration=i.duration, code=i.code))
        timeline = [(parse_image_name(full)[0], at, v) for full, pts in series for at, v in pts]
        await asyncio.to_thread(self.store.save_team, season, round_key, t.division, team, rows, timeline,
                                score_key(t), now)
        self.failed.pop(t.team_number, None)
        took = time.monotonic() - started
        self.pace = took if self.pace is None else 0.8 * self.pace + 0.2 * took
        return True

    async def _work(self, t: TeamScore) -> None:
        try:
            await self.collect(t)
        except Exception as e:
            self.failed[t.team_number] = (score_key(t), self.clock())
            self.last_error = f"{t.team_number}: {e}"
            log.exception("Analysis collection failed for %s", t.team_number)
        finally:
            await asyncio.sleep(PAUSE)
            self.inflight.discard(t.team_number)

    def start_fetches(self, pending: list[TeamScore]) -> int:
        started = 0
        for t in pending:
            if len(self.inflight) >= self.concurrency():
                break
            if t.team_number in self.inflight:
                continue
            self.inflight.add(t.team_number)
            task = asyncio.create_task(self._work(t), name=f"collect-{t.team_number}")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            started += 1
        return started

    # --- places ---

    def refresh(self) -> int:
        """Copy the board's current places etc. onto collected teams whose score hasn't changed."""
        now = self.clock()
        if self._refreshed and now - self._refreshed < REFRESH_EVERY:
            return 0
        self._refreshed = now
        teams = {t.team_number: t for t in self.full_board()}
        changed = 0
        for division in self.divisions():
            by_round: dict[int, dict[str, dict]] = {}
            for team, (round_id, key) in self.store.collected(division).items():
                t = teams.get(team)
                if t is not None and score_key(t) == key:
                    by_round.setdefault(round_id, {})[team] = {
                        "place_division": t.place_division, "place_state_division": t.place_state_division,
                        "play_time": t.play_time, "score_time": t.score_time, "code": t.code, "images": t.images}
            for round_id, rows in by_round.items():
                changed += self.store.refresh_teams(round_id, rows, now)
        return changed

    # --- the loop ---

    async def tick(self) -> int:
        pending = await asyncio.to_thread(self.plan)
        started = self.start_fetches(pending)
        await asyncio.to_thread(self.refresh)
        return started

    async def run(self) -> None:
        await asyncio.sleep(60)  # let the board load
        while True:
            busy = False
            try:
                await self.tick()
                busy = any(s.waiting for s in self.status.values()) or bool(self.inflight)
            except Exception as e:
                self.last_error = str(e)
                log.exception("Analysis collector failed")
            await asyncio.sleep(TICK if busy else IDLE_TICK)

    async def drain(self) -> None:
        for t in list(self.tasks):
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
