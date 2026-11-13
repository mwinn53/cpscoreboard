"""HTTP routes: dashboard pages, JSON API, health check."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .config import Settings
from .events import event_stream
from .poller import Poller
from .sources import ReplaySource, utcnow
from .store import SnapshotStore

RECENT_SECONDS = 300  # rows that changed within this window are highlighted

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _hms(seconds: int | None) -> str:
    if seconds is None:
        return ""
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _ago(when: datetime | None) -> str:
    if when is None:
        return "never"
    secs = int((utcnow() - when).total_seconds())
    if secs < 90:
        return f"{max(secs, 0)}s ago"
    if secs < 5400:
        return f"{secs // 60}m ago"
    if secs < 172800:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _num(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}" if value == int(value) else f"{value:.2f}"


def _signed(value: float) -> str:
    return ("+" if value > 0 else "−") + _num(abs(value))


def _recent(when: datetime | None) -> bool:
    return when is not None and (utcnow() - when).total_seconds() <= RECENT_SECONDS


templates.env.filters.update(hms=_hms, ago=_ago, num=_num, signed=_signed)
templates.env.tests.update(recent=_recent)


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
    stream = event_stream(_poller(request).notifier, request.is_disconnected)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


@router.get("/healthz")
def healthz(request: Request) -> dict[str, Any]:
    return {"status": "ok", **_status(request), "database": _store(request).counts()}
