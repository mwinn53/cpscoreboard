"""The Analysis tab: round samples and their reports (coaches and admins).

* ``/analysis``: pick a division; the round samples (newest first); the sampler's
  status and a button to sample now; for admins, the sampling settings and the
  legacy import.
* ``/analysis/rounds/{id}``: a round's report (app/analysis.py), its label and the
  coaches' notes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from .analysis_legacy import import_files
from .analysis_store import FINAL, PRELIMINARY
from .auth import NotAllowed, _page, require_coach, same_origin
from .devices import Device

log = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis")
MAX_UPLOAD = 60 * 1024 * 1024  # all legacy files together are about 16 MB


def _state(request: Request):
    store, sampler = request.app.state.analysis, request.app.state.sampler
    if store is None:
        raise NotAllowed(404, "Analysis is off here.")
    return store, sampler


def _admin(device: Device) -> None:
    if not device.is_admin:
        raise NotAllowed(403, "Only the admin can change this.")


def _done(path: str, notice: str) -> RedirectResponse:
    sep = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{sep}notice={quote(notice)}", status_code=303)


def _board_divisions(request: Request) -> list[str]:
    poller = request.app.state.poller
    return sorted({t.division for t in poller.full_board if t.division}, key=str.casefold)


@router.get("", response_class=HTMLResponse)
async def analysis_home(request: Request, division: str = "", me: Device = Depends(require_coach)):
    store, sampler = _state(request)
    sampled = await asyncio.to_thread(store.divisions)
    configured = sampler.divisions() if sampler else []
    on_board = _board_divisions(request)
    choices = sorted(set(sampled) | set(configured) | set(on_board), key=str.casefold)
    division = division or (configured[0] if configured else (sampled[0] if sampled else ""))
    rounds = await asyncio.to_thread(store.rounds, division) if division else []
    last = sampler.last_score_change() if sampler else None
    due_at = last + timedelta(hours=sampler.quiet_hours()) if sampler and last else None
    return _page(request, "analysis.html", me=me, division=division, choices=choices, rounds=rounds,
                 on_board=on_board, configured=configured, sampler=sampler, last_change=last, due_at=due_at,
                 notice=request.query_params.get("notice"), error=None)


@router.post("/sample", dependencies=[Depends(same_origin)])
async def sample_now(request: Request, division: Annotated[str, Form()], me: Device = Depends(require_coach)):
    _, sampler = _state(request)
    if sampler is None:
        raise NotAllowed(400, "Sampling needs the live scoreboard (it's off in replay).")
    if division not in _board_divisions(request):
        return _done(f"/analysis?division={quote(division)}", f"No {division} teams on the board right now.")
    if division in sampler.running:
        return _done(f"/analysis?division={quote(division)}", "A sample of this division is already running.")
    log.info("Device %d asked for an analysis sample of %s", me.id, division)
    sampler.start(division)
    return _done(f"/analysis?division={quote(division)}",
                 f"Sampling {division} now; it takes a few minutes. Reload to see it.")


@router.post("/settings", dependencies=[Depends(same_origin)])
async def settings(request: Request, me: Device = Depends(require_coach),
                   divisions: Annotated[list[str] | None, Form()] = None,
                   quiet_hours: Annotated[str, Form()] = "24"):
    _admin(me)
    _, sampler = _state(request)
    if sampler is None:
        raise NotAllowed(400, "Sampling is off here.")
    try:
        hours = max(1.0, min(float(quiet_hours), 240.0))
    except ValueError:
        raise NotAllowed(400, "Quiet hours must be a number.") from None
    await asyncio.to_thread(sampler.set_divisions, [d.strip() for d in divisions or [] if d.strip()])
    await asyncio.to_thread(request.app.state.board.set_value, "analysis_quiet_hours", f"{hours:g}")
    return _done("/analysis", "Saved the sampling settings.")


@router.post("/import", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def import_legacy(request: Request, me: Device = Depends(require_coach),
                        files: Annotated[list[UploadFile], File()] = None):
    _admin(me)
    store, _ = _state(request)
    uploads, total = [], 0
    for f in files or []:
        data = await f.read()
        total += len(data)
        if total > MAX_UPLOAD:
            raise NotAllowed(413, "That's more than 60 MB; upload the round files in smaller batches.")
        uploads.append((f.filename or "", data))
    result = await asyncio.to_thread(import_files, uploads)
    saved = []
    for sample in result.samples:
        info = await asyncio.to_thread(store.save, sample)
        saved.append(info)
    log.info("Device %d imported %d legacy round samples", me.id, len(saved))
    return _page(request, "analysis_import.html", me=me, result=result, saved=saved)


@router.get("/rounds/{round_id}", response_class=HTMLResponse)
async def round_page(request: Request, round_id: int, me: Device = Depends(require_coach)):
    from .analysis import round_report
    store, _ = _state(request)
    info = await asyncio.to_thread(store.get, round_id)
    if info is None:
        raise NotAllowed(404, "No such round sample.")
    board = request.app.state.board
    report = await asyncio.to_thread(round_report, store, info, board.default_state or "GA")
    return _page(request, "analysis_round.html", me=me, info=info, report=report,
                 notice=request.query_params.get("notice"))


@router.post("/rounds/{round_id}", dependencies=[Depends(same_origin)])
async def round_update(request: Request, round_id: int, me: Device = Depends(require_coach),
                       label: Annotated[str, Form()] = "", notes: Annotated[str, Form()] = "",
                       status: Annotated[str, Form()] = ""):
    store, _ = _state(request)
    info = await asyncio.to_thread(store.get, round_id)
    if info is None:
        raise NotAllowed(404, "No such round sample.")
    values = {"label": label.strip()[:100] or info.label, "notes": notes.strip()[:20000]}
    if status in (PRELIMINARY, FINAL):
        values["status"] = status
    try:
        await asyncio.to_thread(store.update_round, round_id, **values)
    except Exception:
        raise NotAllowed(400, "There's already a sample of this round with that status.") from None
    return _done(f"/analysis/rounds/{round_id}", "Saved.")


@router.post("/rounds/{round_id}/delete", dependencies=[Depends(same_origin)])
async def round_delete(request: Request, round_id: int, me: Device = Depends(require_coach)):
    _admin(me)
    store, _ = _state(request)
    info = await asyncio.to_thread(store.get, round_id)
    if info is None:
        raise NotAllowed(404, "No such round sample.")
    await asyncio.to_thread(store.delete_round, round_id)
    log.warning("Device %d deleted analysis sample %s (%s)", me.id, info.title, info.division)
    return _done(f"/analysis?division={quote(info.division)}", f"Deleted {info.title} ({info.status}).")
