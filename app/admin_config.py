"""Admin page for configuration: the scoreboard address, the season (competition start) and posting to X.

Board settings (/admin/board) is about what the scoreboard shows and collects; this
page is about how the app runs around it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Annotated
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import scoreboard_url
from .auth import _page, require_admin, same_origin
from .devices import Device
from .posting import CREDENTIAL_LABELS, CREDENTIALS, KINDS, MODES, Post, PostSettings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/config")


def _render(request: Request, admin: Device, status_code: int = 200, error: str | None = None) -> HTMLResponse:
    state, settings = request.app.state, request.app.state.settings
    monitor, poster = state.monitor, state.poster
    url = scoreboard_url.effective(state.board, settings.scoreboard_url)
    return _page(request, "admin_config.html", status_code, me=admin, error=error,
                 scoreboard_url=url, default_scoreboard_url=settings.scoreboard_url,
                 url_is_default=url == settings.scoreboard_url,
                 replay=settings.scrape_mode.value == "replay",
                 notice=request.query_params.get("notice"),
                 outage=monitor.status() if monitor else None,
                 grace_hours=settings.outage_grace_hours, alert_hours=settings.outage_alert_hours,
                 post=poster.settings(), kinds=KINDS, modes=MODES,
                 credentials=[(k, CREDENTIAL_LABELS[k]) for k in CREDENTIALS],
                 saved_credentials=poster.credentials.saved(),
                 secrets_available=poster.box.available,
                 credentials_ok=poster.credentials.get() is not None,
                 recent=poster.recent(), detail=state.detail,
                 detail_teams=[(n, state.detail.latest.get(n, (None, []))[0]) for n in state.board.watchlist]
                 if state.detail else [])


def _done(notice: str, anchor: str = "") -> RedirectResponse:
    return RedirectResponse(f"/admin/config?notice={quote(notice)}{anchor}", status_code=303)


@router.get("", response_class=HTMLResponse)
async def config_page(request: Request, admin: Device = Depends(require_admin)):
    return _render(request, admin)


@router.post("/scoreboard-url", dependencies=[Depends(same_origin)])
async def set_scoreboard_url(request: Request, admin: Device = Depends(require_admin),
                             url: Annotated[str, Form()] = "", reset: Annotated[str, Form()] = ""):
    """Save a new scoreboard address after a test fetch, or go back to SCOREBOARD_URL."""
    state, default = request.app.state, request.app.state.settings.scoreboard_url
    if reset:
        await asyncio.to_thread(state.board.set_value, scoreboard_url.KEY, "")
        scoreboard_url.apply(state, default)
        log.warning("Admin device %d reset the scoreboard address to the default", admin.id)
        return _done("Back to the default scoreboard address.", "#scoreboard")
    url = url.strip()
    if problem := scoreboard_url.check_format(url):
        return _render(request, admin, 400, error=problem)
    result = await scoreboard_url.test(state.http, url)
    if not result.ok:
        return _render(request, admin, 400, error=f"Not saved: {url} was tested and {result.error}.")
    await asyncio.to_thread(state.board.set_value, scoreboard_url.KEY, "" if url == default else url)
    scoreboard_url.apply(state, url)
    log.warning("Admin device %d set the scoreboard address to %s", admin.id, url)
    teams = f"{result.teams} teams on the board" if result.teams else "a readable but empty board (between rounds?)"
    return _done(f"Saved. The test fetch found {teams}.", "#scoreboard")


@router.post("/competition-start", dependencies=[Depends(same_origin)])
async def competition_start(request: Request, start: Annotated[str, Form()] = "",
                            admin: Device = Depends(require_admin)):
    """Set (or, blank, clear) the competition start the outage alert counts from."""
    monitor = request.app.state.monitor
    if monitor is None:
        return _render(request, admin, 400, error="Outage monitoring is off here (replay mode).")
    when = None
    if start.strip():
        try:  # <input type="datetime-local"> in the display time zone
            tz = ZoneInfo(request.app.state.settings.display_timezone)
            when = datetime.fromisoformat(start.strip()).replace(tzinfo=tz)
        except ValueError:
            return _render(request, admin, 400, error="That date and time couldn't be read.")
    await asyncio.to_thread(monitor.set_competition_start, when)
    log.info("Admin device %d: competition start set to %s", admin.id, when)
    return _done("Saved the competition start." if when else
                 "Cleared the competition start; it will be recorded from the next board with play time.",
                 "#competition-start")


@router.post("/posting", dependencies=[Depends(same_origin)])
async def posting(request: Request, admin: Device = Depends(require_admin),
                  enabled: Annotated[str, Form()] = "", mode: Annotated[str, Form()] = "dry_run",
                  kinds: Annotated[list[str] | None, Form()] = None,
                  change_after_hours: Annotated[str, Form()] = "4", place_every_minutes: Annotated[str, Form()] = "30",
                  per_hour: Annotated[str, Form()] = "10",
                  per_day: Annotated[str, Form()] = "40", footer: Annotated[str, Form()] = ""):
    if mode not in MODES:
        return _render(request, admin, 400, error="Choose dry run or X.")
    try:
        s = PostSettings(enabled=bool(enabled), mode=mode, kinds={k for k in (kinds or []) if k in KINDS},
                         change_after_hours=max(0.0, min(float(change_after_hours), 6.0)),
                         place_every_minutes=max(5, min(int(place_every_minutes), 240)),
                         per_hour=max(0, int(per_hour)), per_day=max(0, int(per_day)), footer=footer.strip()[:100])
    except ValueError:
        return _render(request, admin, 400, error="Hours and limits must be numbers.")
    await asyncio.to_thread(s.save, request.app.state.board)
    log.info("Admin device %d: posting set to %s", admin.id, s)
    return _done("Saved the posting settings.", "#posting")


@router.post("/x-credentials", dependencies=[Depends(same_origin)])
async def x_credentials(request: Request, admin: Device = Depends(require_admin),
                        x_api_key: Annotated[str, Form()] = "", x_api_secret: Annotated[str, Form()] = "",
                        x_access_token: Annotated[str, Form()] = "", x_access_secret: Annotated[str, Form()] = "",
                        clear: Annotated[str, Form()] = ""):
    poster = request.app.state.poster
    if not poster.box.available:
        return _render(request, admin, 400, error="SECRETS_KEY isn't set on the server, so keys can't be saved.")
    values = {"x_api_key": x_api_key, "x_api_secret": x_api_secret,
              "x_access_token": x_access_token, "x_access_secret": x_access_secret}
    if clear:
        for k in CREDENTIALS:
            await asyncio.to_thread(poster.credentials.set, k, "")
        log.warning("Admin device %d cleared the X credentials", admin.id)
        return _done("Cleared the X keys.", "#x-keys")
    changed = [k for k, v in values.items() if v.strip()]
    for k in changed:  # blank fields keep what's saved
        await asyncio.to_thread(poster.credentials.set, k, values[k].strip())
    log.info("Admin device %d updated X credentials: %s", admin.id, ", ".join(changed) or "none")
    return _done(f"Saved {len(changed)} X key{'s' if len(changed) != 1 else ''}." if changed else "Nothing to save.",
                 "#x-keys")


@router.post("/test-post", dependencies=[Depends(same_origin)])
async def test_post(request: Request, admin: Device = Depends(require_admin), text: Annotated[str, Form()] = ""):
    poster = request.app.state.poster
    settings = poster.settings()
    if not settings.enabled:
        return _render(request, admin, 400, error="Posting is turned off; turn it on first.")
    text = text.strip() or f"Test post from {request.app.state.settings.site_title}."
    status = await poster.send(Post("test", "", text), settings, limits=False)
    return _done(f"Test post: {status}.", "#recent-posts")
