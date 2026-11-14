"""Admin page for board settings: watchlist, team aliases, collection filter, legacy import."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .auth import _page, require_admin, same_origin
from .board_config import BoardConfig
from .branding import SLOTS, decode_png
from .devices import Device
from .poller import Poller

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/board")
MAX_UPLOAD = 200_000  # characters; the legacy files are a few hundred bytes


def _board(request: Request) -> BoardConfig:
    return request.app.state.board


def _poller(request: Request) -> Poller:
    return request.app.state.poller


async def _apply(request: Request) -> None:
    """Hand the new filter/watchlist to the poller so it takes effect without a restart."""
    await _poller(request).reconfigure(_board(request).collection_filter())


def _known(request: Request) -> tuple[list[str], list[str]]:
    """States and divisions to offer: everything on the last full board, plus what's configured."""
    poller, board = _poller(request), _board(request)
    teams = poller.full_board or poller.state.teams
    locations = {t.location for t in teams if t.location} | set(board.locations)
    divisions = {t.division for t in teams if t.division} | set(board.divisions)
    return sorted(locations, key=str.casefold), sorted(divisions, key=str.casefold)


def _render(request: Request, admin: Device, status_code: int = 200, error: str | None = None,
            notice: str | None = None) -> HTMLResponse:
    board, poller = _board(request), _poller(request)
    locations, divisions = _known(request)
    by_number = {t.team_number: t for t in poller.full_board or poller.state.teams}
    return _page(request, "admin_board.html", status_code, me=admin, error=error, slots=SLOTS,
                 custom_logos={s for s, v in request.app.state.branding.versions().items() if v},
                 notice=notice or request.query_params.get("notice"),
                 watch=[(n, by_number.get(n)) for n in board.watchlist],
                 aliases=sorted(board.aliases.items()),
                 known_locations=locations, known_divisions=divisions,
                 chosen_locations={v.casefold() for v in board.locations},
                 chosen_divisions={v.casefold() for v in board.divisions},
                 collecting=poller.collect.describe(), default_division=board.default_division,
                 default_state=board.default_state, watch_label=board.watch_label,
                 board_size=poller.state.board_size, collected=len(poller.state.teams))


def _done(notice: str) -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(f"/admin/board?notice={quote(notice)}", status_code=303)


@router.get("", response_class=HTMLResponse, name="admin_board")
async def board_page(request: Request, admin: Device = Depends(require_admin)):
    return _render(request, admin)


@router.post("/watch", dependencies=[Depends(same_origin)])
async def watch_add(request: Request, team: str = Form(""), admin: Device = Depends(require_admin)):
    try:
        added = await asyncio.to_thread(_board(request).add_watch, team)
    except ValueError as e:
        return _render(request, admin, 400, error=str(e))
    await _apply(request)
    team = team.strip()
    log.info("Admin device %d: watch %s", admin.id, team)
    return _done(f"Watching {team}." if added else f"{team} was already on the watchlist.")


@router.post("/watch/{team}/remove", dependencies=[Depends(same_origin)])
async def watch_remove(request: Request, team: str, admin: Device = Depends(require_admin)):
    await asyncio.to_thread(_board(request).remove_watch, team)
    await _apply(request)
    log.info("Admin device %d: unwatch %s", admin.id, team)
    return _done(f"Stopped watching {team}.")


@router.post("/alias", dependencies=[Depends(same_origin)])
async def alias_set(request: Request, team: str = Form(""), alias: str = Form(""),
                    admin: Device = Depends(require_admin)):
    try:
        await asyncio.to_thread(_board(request).set_alias, team, alias)
    except ValueError as e:
        return _render(request, admin, 400, error=str(e))
    team = team.strip()
    log.info("Admin device %d: alias %s = %r", admin.id, team, alias)
    return _done(f"Saved the alias for {team}." if alias.strip() else f"Removed the alias for {team}.")


@router.post("/filter", dependencies=[Depends(same_origin)])
async def filter_set(request: Request, admin: Device = Depends(require_admin),
                     locations: Annotated[list[str], Form()] = [],  # noqa: B006 (FastAPI form default)
                     divisions: Annotated[list[str], Form()] = []):  # noqa: B006
    await asyncio.to_thread(_board(request).set_filter, locations, divisions)
    await _apply(request)
    log.info("Admin device %d: collection filter %s", admin.id, _poller(request).collect.describe())
    return _done(f"Now collecting {_poller(request).collect.describe()}.")


@router.post("/import", dependencies=[Depends(same_origin)])
async def import_legacy(request: Request, team_file: str = Form(""), lookups_file: str = Form(""),
                        admin: Device = Depends(require_admin)):
    if len(team_file) + len(lookups_file) > MAX_UPLOAD:
        return _render(request, admin, 400, error="That's too much text for the legacy files.")
    result = await asyncio.to_thread(_board(request).import_legacy, team_file, lookups_file)
    await _apply(request)
    log.info("Admin device %d: legacy import %s", admin.id, result)
    notice = (f"Imported: {result.watch_added} watched teams added, {result.aliases_added} aliases added, "
              f"{result.aliases_changed} aliases changed.")
    if result.skipped:
        notice += f" Skipped (not team numbers): {', '.join(result.skipped[:10])}."
    return _done(notice)


@router.post("/logo/{slot}", dependencies=[Depends(same_origin)])
async def logo_upload(request: Request, slot: str, image: str = Form(""), admin: Device = Depends(require_admin)):
    if slot not in SLOTS:
        return _render(request, admin, 404, error="Unknown logo.")
    try:
        png = decode_png(image)
    except ValueError as e:
        return _render(request, admin, 400, error=str(e))
    await asyncio.to_thread(request.app.state.branding.set, slot, png)
    log.info("Admin device %d: uploaded the %s logo (%d bytes)", admin.id, slot, len(png))
    return _done(f"Saved the {SLOTS[slot]}.")


@router.post("/logo/{slot}/reset", dependencies=[Depends(same_origin)])
async def logo_reset(request: Request, slot: str, admin: Device = Depends(require_admin)):
    if slot in SLOTS:
        await asyncio.to_thread(request.app.state.branding.clear, slot)
        log.info("Admin device %d: removed the %s logo", admin.id, slot)
    return _done(f"Removed the {SLOTS.get(slot, 'logo')}.")


@router.post("/view", dependencies=[Depends(same_origin)])
async def view_set(request: Request, default_division: str = Form(""), default_state: str = Form(""),
                   watch_label: str = Form(""), admin: Device = Depends(require_admin)):
    await asyncio.to_thread(_board(request).set_view, default_division, default_state, watch_label)
    log.info("Admin device %d: default view %r / %r, watch label %r", admin.id, default_division, default_state,
             watch_label)
    return _done("Saved the scoreboard view.")
