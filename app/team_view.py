"""A team's history: the /teams/{n} page and the scoreboard's expandable sparkline rows.

The page has two sections:

* **Placement**: District, State and National place over time (the scoreboard's
  column order), each its own chart with 1st at the top.
* **Scoring**: total score over time, then per-image detail like the official
  team page: the image table and one chart of every image's score. For the
  current round these come straight from the public scoreboard (any team, cached a
  minute); otherwise from what the app stored for watched teams (app/team_detail.py).

District place isn't on the public board; it's each district team's rank by
national place among the district teams (district schools plus watched teams) in
its division, so its history is rebuilt from those teams' stored snapshots.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .auth import require_viewer
from .charts import multi_step_chart, short_image_name, sparkline, split_rounds, step_chart
from .store import Snapshot, SnapshotStore
from .team_detail import OfficialDetail
from .templating import _num, templates

router = APIRouter(dependencies=[Depends(require_viewer)])

CURRENT_GAP = timedelta(hours=12)  # data this recent still belongs to the current round
PLACE_WIDTH, SCORE_WIDTH = 420, 620    # SVG widths near how wide each chart shows (3 and 2 per row)


class BoardCache:
    """Results that only change when the board does (keyed by the poller's change count), shared by all viewers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._version: object = None
        self._data: dict = {}

    def get(self, version: object, key, build):
        with self._lock:
            if version != self._version:
                self._version, self._data = version, {}
            if key in self._data:
                return self._data[key]
        value = build()
        with self._lock:
            if version == self._version:
                self._data[key] = value
        return value


def _cache(request: Request) -> tuple[BoardCache, object]:
    state = request.app.state
    if getattr(state, "board_cache", None) is None:
        state.board_cache = BoardCache()
    poller = state.poller
    return state.board_cache, (id(state.store), poller.state.changes_seen, poller.state.data_as_of)


def district_history(store: SnapshotStore, team: str, district: Iterable[str]) -> list[tuple[datetime, int]]:
    """The team's district place at each change of any district team's national place."""
    histories = {n: store.history(n, limit=10000) for n in set(district) | {team}}
    events = sorted((s.observed_at, n, s.team.place_division, s.team.division)
                    for n, snaps in histories.items() for s in snaps)
    current: dict[str, tuple[int, str]] = {}
    out: list[tuple[datetime, int]] = []
    i = 0
    while i < len(events):
        at = events[i][0]
        while i < len(events) and events[i][0] == at:  # apply everything at this instant
            _, n, place, division = events[i]
            current[n] = (place, division)
            i += 1
        if team not in current:
            continue
        mine, div = current[team]
        rank = 1 + sum(1 for n, (p, d) in current.items() if n != team and d == div and p < mine)
        if not out or out[-1][1] != rank:
            out.append((at, rank))
    return out


def _window(points: list[tuple[datetime, float]], start: datetime, stop: datetime) -> list[tuple[datetime, float]]:
    """Points within [start, stop], starting with the value that held at ``start``."""
    before = [p for p in points if p[0] <= start]
    inside = [p for p in points if start < p[0] <= stop]
    return ([(start, before[-1][1])] if before else []) + inside


def _place_fmt(v: float) -> str:
    return f"{v:.0f}"


def _round(snapshots: list[Snapshot], round: int, as_of: datetime | None):
    """(runs newest first, chosen index, its snapshots, end time) for a team's history."""
    runs = list(reversed(split_rounds([s.observed_at for s in snapshots])))
    if not runs:
        return runs, 0, [], None
    round = max(0, min(round, len(runs) - 1))
    start, end = runs[round]
    snaps = snapshots[start:end]
    until = snaps[-1].observed_at
    if round == 0 and as_of and as_of > until and as_of - until < CURRENT_GAP:
        until = as_of  # the current round: the last value still holds now
    return runs, round, snaps, until


def _context(request: Request, team: str, round: int, official: OfficialDetail | None) -> dict[str, Any]:
    state = request.app.state
    store, poller, board = state.store, state.poller, state.board
    tz = ZoneInfo(state.settings.display_timezone)
    snapshots = store.history(team, limit=10000)
    current = {t.team_number: t for t in (poller.full_board or poller.state.teams)}.get(team)
    if not snapshots and current is None:
        raise HTTPException(404, f"No team {team}")
    runs, round, snaps, until = _round(snapshots, round, poller.state.data_as_of)
    district = set(board.aliases) | set(board.watchlist)

    placement, scoring, rows = [], [], []
    image_table, image_chart, image_source = [], None, ""
    if snaps:
        start = snaps[0].observed_at
        place_opts = {"invert": True, "integer": True, "fmt": _place_fmt, "width": PLACE_WIDTH}
        if team in district:
            cache, version = _cache(request)
            dh = _window([(t, float(p)) for t, p in cache.get(
                version, ("district", team), lambda: district_history(store, team, district))], start, until)
            if dh:
                placement.append(("District", step_chart(dh, until, tz=tz, label=f"District place for {team}",
                                                         **place_opts)))
        for title, attr in (("State", "place_state_division"), ("National", "place_division")):
            pts = [(s.observed_at, getattr(s.team, attr)) for s in snaps]
            placement.append((title, step_chart(pts, until, tz=tz, label=f"{title} place for {team}", **place_opts)))
        score = [(s.observed_at, s.team.score) for s in snaps if s.team.score is not None]
        if score:
            scoring.append(("Total score", step_chart(score, until, tz=tz, label=f"Total score for {team}", fmt=_num,
                                                      width=SCORE_WIDTH)))
        rows = list(reversed(snaps))

        # Per-image: the official board for the current round, else what was stored (watched teams).
        series: list[tuple[str, list[tuple[datetime, float]]]] = []
        if round == 0 and official is not None:
            image_table = official.images
            recent = [(n, p) for n, p in official.history if p and p[-1][0] >= start - timedelta(hours=1)]
            if recent:
                series, image_source = recent, "official"
                until = max(until, official.fetched_at)
        detail = getattr(state, "detail", None)
        if not series and detail is not None and detail.store is not None:
            stop = until + CURRENT_GAP
            by_image: dict[str, list[tuple[datetime, float]]] = {}
            for h in detail.store.history(team):
                if start - timedelta(hours=1) <= h.observed_at <= stop and h.image.ccs_score is not None:
                    by_image.setdefault(h.image.image, []).append((h.observed_at, h.image.ccs_score))
            series = sorted(by_image.items())
            if series:
                image_source = "stored"
            if not image_table and round == 0 and team in detail.latest:
                image_table = detail.latest[team][1]
                image_source = image_source or "stored"
        if series:
            image_chart = multi_step_chart(series, until, tz=tz, label=f"Image scores for {team}", fmt=_num,
                                           width=SCORE_WIDTH)

    return {"team_number": team, "school": board.schools.get(team, ""), "current": current,
            "rounds": [snapshots[s].observed_at for s, _ in runs], "round": round,
            "placement": placement, "scoring": scoring, "rows": rows,
            "images": image_table, "image_chart": image_chart, "image_source": image_source,
            "image_names": [short_image_name(i.image) for i in image_table],
            "image_legend": [short_image_name(n) for n, _ in (series if snaps and series else [])]}


def stored_official(state, team: str):
    """The team's per-image detail as the collector stored it, while its score is still what it was then.

    Saves two requests to the public scoreboard per team-page view once a team has finished; teams still
    playing (or changed since) are fetched live."""
    from .analysis_collector import score_key
    from .team_detail import ImageScore, OfficialDetail
    analysis, poller = getattr(state, "analysis", None), getattr(state, "poller", None)
    if analysis is None or poller is None:
        return None
    current = next((t for t in poller.full_board if t.team_number == team), None)
    entry = analysis.latest_collection(team) if current is not None else None
    if entry is None or entry[1] != score_key(current):
        return None
    images, timeline = analysis.team_detail(entry[0], team)
    if not images:
        return None
    history: dict[str, list[tuple[datetime, float]]] = {}
    for image, at, score in timeline:
        history.setdefault(image, []).append((at, score))
    return OfficialDetail([ImageScore(i.image_full or i.image, i.duration, i.found, i.remaining, i.penalties, i.code,
                                      i.score) for i in images], sorted(history.items()), entry[2])


@router.get("/teams/{team_number}", response_class=HTMLResponse)
async def team_page(request: Request, team_number: str, round: int = 0):
    """A team's placement and scoring over time, one round at a time (newest first)."""
    client = getattr(request.app.state, "official", None)
    official = None
    if round == 0:
        official = await asyncio.to_thread(stored_official, request.app.state, team_number)
        if official is None and client is not None:
            official = await client.get(team_number)
    ctx = await asyncio.to_thread(_context, request, team_number, round, official)
    return templates.TemplateResponse(request, "team.html", ctx)


def _spark_context(request: Request, team: str) -> dict[str, Any]:
    state = request.app.state
    store, poller, board = state.store, state.poller, state.board
    snapshots = store.history(team, limit=10000)
    _, _, snaps, until = _round(snapshots, 0, poller.state.data_as_of)
    sparks = []
    if snaps:
        start, last = snaps[0].observed_at, snaps[-1].team
        district = set(board.aliases) | set(board.watchlist)
        sparks.append(("Total score", _num(last.score),
                       sparkline([(s.observed_at, s.team.score) for s in snaps], until, label=f"Total score for {team}")))
        if team in district:
            cache, version = _cache(request)
            dh = _window([(t, float(p)) for t, p in cache.get(
                version, ("district", team), lambda: district_history(store, team, district))], start, until)
            if dh:
                sparks.append(("District", f"{dh[-1][1]:.0f}",
                               sparkline(dh, until, invert=True, label=f"District place for {team}")))
        for title, attr in (("State", "place_state_division"), ("National", "place_division")):
            sparks.append((title, str(getattr(last, attr)),
                           sparkline([(s.observed_at, getattr(s.team, attr)) for s in snaps], until, invert=True,
                                     label=f"{title} place for {team}")))
    return {"team_number": team, "sparks": sparks, "since": snaps[0].observed_at if snaps else None}


@router.get("/partials/spark/{team_number}", response_class=HTMLResponse)
async def spark_partial(request: Request, team_number: str):
    """The expanded row under a team on the scoreboard: this round's sparklines (built once per board change)."""
    cache, version = _cache(request)
    html = await asyncio.to_thread(cache.get, version, ("spark", team_number), lambda: templates.get_template(
        "_spark.html").render(_spark_context(request, team_number)))
    return HTMLResponse(html)
