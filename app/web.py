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


def _board(request: Request, q: str, division: str, state: str, limit: int) -> dict[str, Any]:
    settings, st = _settings(request), _poller(request).state
    rows = st.teams
    if division:
        rows = [t for t in rows if t.division == division]
    if state:
        rows = [t for t in rows if t.location == state]
    if q:
        needle = q.strip().lower()
        rows = [t for t in rows if needle in t.team_number.lower()]
    watch = settings.watch_team_list
    return {
        "status": _status(request),
        "watched": [st.by_number[n] for n in watch if n in st.by_number],
        "watch_missing": [n for n in watch if n not in st.by_number],
        "watch_set": set(watch),
        "changes": st.changes,
        "rows": rows[:limit] if limit > 0 else rows,
        "matched": len(rows),
        "has_totals": any(t.total is not None for t in st.teams),
        "has_tier": any(t.tier for t in st.teams),
        "divisions": sorted({t.division for t in st.teams if t.division}),
        "states": sorted({t.location for t in st.teams if t.location}),
        "filters": {"q": q, "division": division, "state": state, "limit": limit},
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, q: str = "", division: str = "", state: str = "", limit: int = 100):
    return templates.TemplateResponse(request, "dashboard.html", _board(request, q, division, state, limit))


@router.get("/partials/board", response_class=HTMLResponse)
def board_partial(request: Request, q: str = "", division: str = "", state: str = "", limit: int = 100):
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
    st = _poller(request).state
    return {"data_as_of": st.data_as_of, "teams": [t.to_dict() for t in st.teams]}


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
