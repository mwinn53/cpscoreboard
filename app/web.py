"""HTTP routes for the scoreboard: dashboard pages, JSON API, events, health check.

Everything except /healthz requires an approved device (see app/auth.py).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from .auth import require_viewer
from .config import Settings
from .events import event_stream
from .poller import Poller
from .scraper import TeamScore
from .sources import ReplaySource
from .store import SnapshotStore
from .templating import templates

router = APIRouter(dependencies=[Depends(require_viewer)])
public_router = APIRouter()


def _poller(request: Request) -> Poller:
    return request.app.state.poller


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _store(request: Request) -> SnapshotStore:
    return request.app.state.store


def _status(request: Request) -> dict[str, Any]:
    settings, poller = _settings(request), _poller(request)
    st = poller.state
    status: dict[str, Any] = {
        "env": settings.app_env.value,
        "mode": settings.scrape_mode.value,
        "source": poller.source.description,
        "teams": len(st.teams),
        "board_size": st.board_size,
        "collecting": poller.collect.describe(),
        "data_as_of": st.data_as_of,
        "last_changed": st.last_changed,
        "last_error": st.last_error,
        "polls": st.polls,
        "changes": st.changes_seen,
        "finished": st.finished,
        "restored": st.restored,
    }
    if isinstance(poller.source, ReplaySource):
        status["replay_position"] = poller.source.position
    return status


ALL = "all"  # filter value meaning "every division" / "every state"

# The public scoreboard's own key for the warning letters.
WARNING_CODES = {"M": "Multiple Instances", "S": "Clock Skew", "T": "Time Exceeded", "U": "Multiple UIDs"}


def _default(chosen: str, configured: tuple[str, ...], options: list[str]) -> str:
    """Where the dashboard opens: the admin's default view; if unset, the collection filter's
    division/state when it names exactly one; otherwise all."""
    value = chosen or (configured[0] if len(configured) == 1 else ALL)
    if value.casefold() == ALL:
        return ALL
    match = [o for o in options if o.casefold() == value.casefold()]
    return match[0] if match else value


def district_places(teams: list[TeamScore], district: set[str]) -> dict[str, int]:
    """Place of each district team among the district teams in its division (by national place)."""
    places: dict[str, int] = {}
    seen: dict[str, int] = {}
    for t in sorted((t for t in teams if t.team_number in district), key=lambda t: t.place_division):
        seen[t.division] = seen.get(t.division, 0) + 1
        places[t.team_number] = seen[t.division]
    return places


def _board(request: Request, q: str, division: str | None, state: str | None, limit: int) -> dict[str, Any]:
    poller, board = _poller(request), request.app.state.board
    st = poller.state
    # Show the whole live board; the collection filter only limits what's stored as history.
    # Right after a restart that's just the restored (collected) teams until the first poll.
    teams = poller.full_board or st.teams
    by_number = {t.team_number: t for t in teams}
    aliases = board.aliases
    divisions = sorted({t.division for t in teams if t.division})
    states = sorted({t.location for t in teams if t.location})
    division = _default(board.default_division, board.divisions, divisions) if division is None else (division or ALL)
    state = _default(board.default_state, board.locations, states) if state is None else (state or ALL)

    rows = teams
    if division != ALL:
        rows = [t for t in rows if t.division.casefold() == division.casefold()]
    if state != ALL:
        rows = [t for t in rows if t.location.casefold() == state.casefold()]
    if q:
        needle = q.strip().lower()
        rows = [t for t in rows
                if needle in t.team_number.lower() or needle in aliases.get(t.team_number, "").lower()]
    watch = board.watchlist
    watched = [by_number[n] for n in watch if n in by_number]

    def columns(shown: list[TeamScore]) -> dict[str, bool]:
        """State/division columns only when the filter doesn't already say what they are."""
        return {
            "state": state == ALL or any(t.location.casefold() != state.casefold() for t in shown),
            "division": division == ALL or any(t.division.casefold() != division.casefold() for t in shown),
            "tier": any(t.tier for t in shown) and division == ALL,
        }

    shown = rows[:limit] if limit > 0 else rows
    return {
        "status": _status(request),
        "watched": watched,
        "watch_missing": [n for n in watch if n not in by_number],
        "watch_set": set(watch),
        "watch_label": board.watch_label,
        "warning_codes": WARNING_CODES,
        "aliases": aliases,
        # District = the named district schools' teams plus the watched (e.g. EMS) teams.
        "district": district_places(teams, set(aliases) | set(watch)),
        "changes": st.changes,
        "rows": shown,
        "matched": len(rows),
        "shown_on_board": len(teams),
        "cols": columns(shown),
        "watch_cols": columns(watched),
        "has_totals": any(t.total is not None for t in teams),
        "divisions": divisions,
        "states": states,
        "refresh": max(5, round(_settings(request).poll_interval)),
        "filters": {"q": q, "division": division, "state": state, "limit": limit},
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, q: str = "", division: str | None = None, state: str | None = None,
              limit: int = 0):
    return templates.TemplateResponse(request, "dashboard.html", _board(request, q, division, state, limit))


@router.get("/partials/board", response_class=HTMLResponse)
def board_partial(request: Request, q: str = "", division: str | None = None, state: str | None = None,
                  limit: int = 0):
    return templates.TemplateResponse(request, "_board.html", _board(request, q, division, state, limit))


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Server-sent events: ``board`` whenever the scoreboard changes."""
    device = getattr(request.state, "device", None)
    still_allowed = None
    if device is not None:
        devices = request.app.state.devices

        async def still_allowed() -> bool:  # a revoked device's open stream ends at the next heartbeat
            current = await asyncio.to_thread(devices.get, device.id)
            return current is not None and current.approved

    stream = event_stream(_poller(request).notifier, request.is_disconnected, still_allowed=still_allowed)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/status")
def api_status(request: Request) -> dict[str, Any]:
    return {**_status(request), "database": _store(request).counts()}


@router.get("/api/scores")
def api_scores(request: Request) -> dict[str, Any]:
    st, aliases = _poller(request).state, request.app.state.board.aliases
    return {"data_as_of": st.data_as_of,
            "teams": [{**t.to_dict(), "alias": aliases.get(t.team_number, "")} for t in st.teams]}


@router.get("/api/teams/{team_number}/history")
def api_team_history(request: Request, team_number: str, limit: int = 1000) -> dict[str, Any]:
    snapshots = _store(request).history(team_number, limit=max(1, min(limit, 10000)))
    if not snapshots:
        raise HTTPException(404, f"No history for team {team_number}")
    return {"team_number": team_number,
            "snapshots": [{"observed_at": s.observed_at, **s.team.to_dict()} for s in snapshots]}


@public_router.get("/healthz")
def healthz(request: Request) -> dict[str, Any]:
    """Liveness for Docker and the deploy check. Public, so it reveals nothing about the board."""
    _store(request).counts()  # raises (500) if the database is unusable
    return {"status": "ok"}
