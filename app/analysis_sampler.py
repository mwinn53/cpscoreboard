"""Take a round sample once scoring has gone quiet (issue: Analysis tab).

Every ``CHECK_EVERY`` the sampler looks at the full board the poller keeps:

* It tracks when any team's **score last changed** (play time ticking doesn't
  count), kept in ``app_settings`` so a restart doesn't reset the clock.
* When the board has played teams and no score has changed for ``quiet_hours``
  (24 by default; usually about 72 hours after the round starts), each division in
  the analysis setting (Middle School by default) is sampled, unless a sample of
  that round already includes the latest scores.

Sampling a division fetches, for each of its teams, the team detail (challenge
scores and the official total), the per-image table and the 5-minute image history
from the public scoreboard: three gentle requests per team, a few at a time.
Coaches can also sample a division on demand from the Analysis tab.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from .analysis_store import (DISTRICT, EMS, LIVE, PRELIMINARY, AnalysisStore, ImageRow, RoundInfo, Sample, TeamRow,
                             parse_image_name, round_identity)
from .board_config import BoardConfig
from .scraper import TeamScore
from .team_detail import _float, chart_url, detail_url, parse_image_chart, parse_images

log = logging.getLogger(__name__)

DIVISIONS_KEY, QUIET_KEY = "analysis_divisions", "analysis_quiet_hours"
LAST_CHANGE_KEY, DIGEST_KEY = "analysis_last_score_change", "analysis_score_digest"
DEFAULT_DIVISIONS, DEFAULT_QUIET_HOURS = "Middle School", 24.0
CHECK_EVERY = 900          # seconds
CONCURRENCY, PAUSE = 3, 0.2


def score_digest(teams: list[TeamScore]) -> str:
    """Changes only when a score does (not play time)."""
    key = sorted((t.team_number, t.ccs_score, t.total, t.adjustment) for t in teams)
    return hashlib.sha256(json.dumps(key, default=str).encode()).hexdigest()


class AnalysisSampler:
    def __init__(self, store: AnalysisStore, board: BoardConfig, client: httpx.AsyncClient,
                 full_board: Callable[[], list[TeamScore]], scoreboard_url: Callable[[], str],
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.store, self.board, self.client = store, board, client
        self.full_board, self.scoreboard_url, self.clock = full_board, scoreboard_url, clock
        self.running: set[str] = set()      # divisions being sampled now
        self._tasks: set[asyncio.Task] = set()
        self.last_error: str = ""

    # --- settings ---

    def divisions(self) -> list[str]:
        raw = self.board.get_value(DIVISIONS_KEY)
        return [d for d in (raw.split("|") if raw else [DEFAULT_DIVISIONS]) if d]

    def set_divisions(self, divisions: list[str]) -> None:
        self.board.set_value(DIVISIONS_KEY, "|".join(divisions) if divisions else "|")

    def quiet_hours(self) -> float:
        try:
            return float(self.board.get_value(QUIET_KEY) or DEFAULT_QUIET_HOURS)
        except ValueError:
            return DEFAULT_QUIET_HOURS

    def last_score_change(self) -> datetime | None:
        raw = self.board.get_value(LAST_CHANGE_KEY)
        return datetime.fromisoformat(raw) if raw else None

    # --- the timer ---

    def note_board(self, teams: list[TeamScore]) -> None:
        """Record the time whenever any score on the board changed."""
        if not teams:
            return
        digest = score_digest(teams)
        if digest != self.board.get_value(DIGEST_KEY):
            self.board.set_value(DIGEST_KEY, digest)
            self.board.set_value(LAST_CHANGE_KEY, self.clock().isoformat(timespec="seconds"))

    def due(self, teams: list[TeamScore]) -> list[str]:
        """Divisions to sample now."""
        last = self.last_score_change()
        if last is None or not any(t.play_time for t in teams):
            return []
        if self.clock() - last < timedelta(hours=self.quiet_hours()):
            return []
        out = []
        for division in self.divisions():
            if not any(t.division == division for t in teams) or division in self.running:
                continue
            done = [r for r in self.store.rounds(division) if r.source == LIVE and r.sampled_at >= last]
            if not done:
                out.append(division)
        return out

    async def check(self) -> list[RoundInfo]:
        teams = self.full_board()
        await asyncio.to_thread(self.note_board, teams)
        samples = []
        for division in await asyncio.to_thread(self.due, teams):
            log.info("Scoring has been quiet for %g h: sampling %s", self.quiet_hours(), division)
            info = await self.sample(division)
            if info:
                samples.append(info)
        return samples

    async def run(self) -> None:
        await asyncio.sleep(60)  # let the board load
        while True:
            try:
                await self.check()
            except Exception as e:
                self.last_error = str(e)
                log.exception("Analysis sampler failed")
            await asyncio.sleep(CHECK_EVERY)

    # --- sampling ---

    def _groups(self) -> dict[str, tuple[str, str]]:
        """team -> (name, group) from the watchlist (EMS) and the district schools."""
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
                    log.info("Sample fetch %s for %s failed: %s", url, team, e)
                await asyncio.sleep(2)
        return None

    async def _team(self, team: TeamScore, base: str, sem: asyncio.Semaphore, now: datetime):
        async with sem:
            detail = await self._get(base, team.team_number)
            images = await self._get(detail_url(base), team.team_number)
            chart = await self._get(chart_url(base), team.team_number)
            await asyncio.sleep(PAUSE)
        extra = {}
        if detail:
            try:
                rows = json.loads(detail).get("data") or [{}]
                extra = rows[0] if isinstance(rows, list) and rows else {}
            except ValueError:
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
        return team, extra, img_rows, series

    def start(self, division: str) -> None:
        """Sample in the background (the Analysis tab's button); keeps a reference so the task isn't lost."""
        task = asyncio.create_task(self.sample(division), name=f"sample-{division}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def sample(self, division: str) -> RoundInfo | None:
        """Sample one division from the current board now."""
        teams = [t for t in self.full_board() if t.division == division]
        if not teams:
            return None
        self.running.add(division)
        try:
            now = self.clock()
            base = self.scoreboard_url()
            sem = asyncio.Semaphore(CONCURRENCY)
            results = await asyncio.gather(*(self._team(t, base, sem, now) for t in teams))
            groups = self._groups()
            team_rows, image_rows, timeline, full_names = [], [], [], []
            for t, extra, imgs, series in results:
                name, grp = groups.get(t.team_number, ("", ""))
                team_rows.append(TeamRow(
                    team_number=t.team_number, location=t.location, tier=t.tier, name=name, grp=grp,
                    images=t.images, play_time=t.play_time, score_time=t.score_time, ccs_score=t.ccs_score,
                    challenge_1=_float(extra.get("score_1")), challenge_2=_float(extra.get("score_2")),
                    adjustment=_float(extra.get("adjustment")) if extra.get("adjustment") is not None else t.adjustment,
                    total=_float(extra.get("total")) if extra.get("total") is not None else t.total,
                    code=t.code, place_division=t.place_division, place_state_division=t.place_state_division))
                for i in imgs:
                    short, _, _ = parse_image_name(i.image)
                    full_names.append(i.image)
                    image_rows.append(ImageRow(team_number=t.team_number, image=short, image_full=i.image,
                                               found=i.found, remaining=i.remaining, penalties=i.penalties,
                                               score=i.ccs_score, duration=i.duration, code=i.code))
                for full, pts in series:
                    short, _, _ = parse_image_name(full)
                    timeline.extend((t.team_number, short, at, v) for at, v in pts)
            season, round_key = round_identity(full_names, [t.team_number for t in teams])
            if season is None:
                self.last_error = f"couldn't tell which season {division}'s round is from"
                log.warning("Analysis sample for %s skipped: %s", division, self.last_error)
                return None
            info = await asyncio.to_thread(self.store.save, Sample(
                season=season, round_key=round_key or "round", division=division, status=PRELIMINARY,
                source=LIVE, sampled_at=now, teams=team_rows, images=image_rows, timeline=timeline))
            self.last_error = ""
            log.info("Analysis sample: %s %s, %d teams, %d image rows, %d timeline points",
                     info.title, division, len(team_rows), len(image_rows), len(timeline))
            return info
        finally:
            self.running.discard(division)

