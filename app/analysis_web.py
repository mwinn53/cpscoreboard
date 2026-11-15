"""The Analysis tab: data sets and their reports (coaches and admins).

* ``/analysis``: pick a division; its reports (one per data set, by season); the
  collection status (teams collected, waiting, still playing, ETA), refreshed every
  30 seconds; for admins, the throttle (teams fetched at once), the divisions to
  collect and the legacy import.
* ``/analysis/reports/{id}``: a round's report (app/analysis.py,
  app/analysis_narrative.py, app/analysis_charts.py), its name and the coaches' notes.
* ``/analysis/seasons``: season over season; ``/analysis/seasons/{season}``: a
  season's rounds; ``/analysis/compare?a=&b=``: any two reports side by side
  (app/analysis_compare.py).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from .analysis_collector import MAX_CONCURRENCY
from .analysis_legacy import import_files
from .analysis_store import FINAL, LIVE, PRELIMINARY
from .auth import NotAllowed, _page, require_coach, same_origin
from .devices import Device

log = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis")
MAX_UPLOAD = 60 * 1024 * 1024  # all legacy files together are about 16 MB
TOP_CHOICES = (10, 25, 50, 100)


def _state(request: Request):
    store, collector = request.app.state.analysis, request.app.state.collector
    if store is None:
        raise NotAllowed(404, "Analysis is off here.")
    return store, collector


def _home_state(request: Request) -> str:
    return request.app.state.board.default_state or "GA"


def _admin(device: Device) -> None:
    if not device.is_admin:
        raise NotAllowed(403, "Only the admin can change this.")


def _done(path: str, notice: str) -> RedirectResponse:
    sep = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{sep}notice={quote(notice)}", status_code=303)


def _board_divisions(request: Request) -> list[str]:
    poller = request.app.state.poller
    return sorted({t.division for t in poller.full_board if t.division}, key=str.casefold)


def _division(request: Request, store, collector, division: str) -> tuple[str, list[str]]:
    sampled = store.divisions()
    configured = collector.divisions() if collector else []
    choices = sorted(set(sampled) | set(configured) | set(_board_divisions(request)), key=str.casefold)
    return division or (configured[0] if configured else (sampled[0] if sampled else "")), choices


async def _get_round(store, round_id: int):
    info = await asyncio.to_thread(store.get, round_id)
    if info is None:
        raise NotAllowed(404, "No such report.")
    return info


def _collection(request: Request, collector, division: str) -> dict:
    return {"collector": collector, "division": division,
            "configured": collector.divisions() if collector else [],
            "status": collector.status.get(division) if collector else None,
            "max_concurrency": MAX_CONCURRENCY}


@router.get("", response_class=HTMLResponse)
async def analysis_home(request: Request, division: str = "", me: Device = Depends(require_coach)):
    store, collector = _state(request)
    division, choices = await asyncio.to_thread(_division, request, store, collector, division)
    rounds = await asyncio.to_thread(store.rounds, division) if division else []
    seasons: dict[int, list] = {}
    for r in rounds:
        seasons.setdefault(r.season, []).append(r)
    return _page(request, "analysis.html", me=me, choices=choices, rounds=rounds, seasons=seasons,
                 on_board=_board_divisions(request), notice=request.query_params.get("notice"),
                 **_collection(request, collector, division))


@router.get("/partials/collection", response_class=HTMLResponse)
async def collection_partial(request: Request, division: str = "", me: Device = Depends(require_coach)):
    _, collector = _state(request)
    return _page(request, "_analysis_collection.html", me=me, **_collection(request, collector, division))


@router.post("/settings", dependencies=[Depends(same_origin)])
async def settings(request: Request, me: Device = Depends(require_coach),
                   divisions: Annotated[list[str] | None, Form()] = None, division: Annotated[str, Form()] = ""):
    _admin(me)
    _, collector = _state(request)
    if collector is None:
        raise NotAllowed(400, "Collection is off here (replay).")
    await asyncio.to_thread(collector.set_divisions, [d.strip() for d in divisions or [] if d.strip()])
    back = f"/analysis?division={quote(division)}" if division else "/analysis"
    return _done(back, "Saved the divisions to collect.")


@router.post("/throttle", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def throttle(request: Request, me: Device = Depends(require_coach),
                   concurrency: Annotated[str, Form()] = "1", division: Annotated[str, Form()] = ""):
    """The slider: save, then return the refreshed status (htmx) or go back to the page."""
    _admin(me)
    _, collector = _state(request)
    if collector is None:
        raise NotAllowed(400, "Collection is off here (replay).")
    try:
        await asyncio.to_thread(collector.set_concurrency, int(concurrency))
    except ValueError:
        raise NotAllowed(400, "The throttle must be a whole number.") from None
    await asyncio.to_thread(collector.plan)
    if request.headers.get("HX-Request"):
        return _page(request, "_analysis_collection.html", me=me, **_collection(request, collector, division))
    return _done(f"/analysis?division={quote(division)}", "Saved the throttle.")


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
    log.info("Device %d imported %d legacy data sets", me.id, len(saved))
    return _page(request, "analysis_import.html", me=me, result=result, saved=saved)


# --- reports ---

@router.get("/rounds/{round_id}")
async def old_round_link(round_id: int):
    return RedirectResponse(f"/analysis/reports/{round_id}", status_code=301)


@router.get("/reports/{round_id}", response_class=HTMLResponse)
async def report_page(request: Request, round_id: int, top: int = 25, me: Device = Depends(require_coach)):
    from .analysis import cached_report
    from .analysis_charts import progress_legend, round_charts, team_legend
    from .analysis_compare import round_context
    store, collector = _state(request)
    info = await _get_round(store, round_id)
    state = _home_state(request)

    def build():
        report = cached_report(store, info, state)
        return report, round_charts(report), round_context(store, info, state)
    report, charts, context = await asyncio.to_thread(build)
    status = None
    if collector and info.source == LIVE:
        st = collector.status.get(info.division)
        status = st if st and st.round_id == info.id and not st.complete else None
    top = top if top in TOP_CHOICES else 25
    others = [r for r in await asyncio.to_thread(store.rounds, info.division) if r.id != info.id]
    return _page(request, "analysis_round.html", me=me, info=info, report=report, charts=charts, context=context,
                 legend=team_legend(state), progress_legend=progress_legend(report), status=status, top=top,
                 top_choices=TOP_CHOICES, others=others, notice=request.query_params.get("notice"))


@router.post("/reports/{round_id}", dependencies=[Depends(same_origin)])
async def report_update(request: Request, round_id: int, me: Device = Depends(require_coach),
                        label: Annotated[str, Form()] = "", notes: Annotated[str, Form()] = "",
                        status: Annotated[str, Form()] = ""):
    store, _ = _state(request)
    info = await _get_round(store, round_id)
    values = {"label": label.strip()[:100] or info.label, "notes": notes.strip()[:20000]}
    if status in (PRELIMINARY, FINAL):
        values["status"] = status
    try:
        await asyncio.to_thread(store.update_round, round_id, **values)
    except Exception:
        raise NotAllowed(400, "There's already a data set of this round with that status.") from None
    return _done(f"/analysis/reports/{round_id}", "Saved.")


@router.post("/reports/{round_id}/delete", dependencies=[Depends(same_origin)])
async def report_delete(request: Request, round_id: int, me: Device = Depends(require_coach)):
    _admin(me)
    store, _ = _state(request)
    info = await _get_round(store, round_id)
    await asyncio.to_thread(store.delete_round, round_id)
    log.warning("Device %d deleted the data set %s (%s)", me.id, info.title, info.division)
    return _done(f"/analysis?division={quote(info.division)}", f"Deleted {info.title} ({info.status}).")


# --- comparisons ---

@router.get("/seasons", response_class=HTMLResponse)
async def seasons_page(request: Request, division: str = "", me: Device = Depends(require_coach)):
    from .analysis_compare import history_view
    store, collector = _state(request)
    division, choices = await asyncio.to_thread(_division, request, store, collector, division)
    view = await asyncio.to_thread(history_view, store, division, _home_state(request))
    return _page(request, "analysis_seasons.html", me=me, view=view, division=division, choices=choices)


@router.get("/seasons/{season}", response_class=HTMLResponse)
async def season_page(request: Request, season: int, division: str = "", me: Device = Depends(require_coach)):
    from .analysis_compare import season_view
    store, collector = _state(request)
    division, _ = await asyncio.to_thread(_division, request, store, collector, division)
    view = await asyncio.to_thread(season_view, store, division, season, _home_state(request))
    if not view.summaries:
        raise NotAllowed(404, f"No CP-{season} reports for {division}.")
    return _page(request, "analysis_season.html", me=me, view=view, division=division)


@router.get("/compare", response_class=HTMLResponse)
async def compare_page(request: Request, a: int, b: int, me: Device = Depends(require_coach)):
    from .analysis_compare import pair_view
    store, _ = _state(request)
    ia, ib = await _get_round(store, a), await _get_round(store, b)
    if ia.division != ib.division:
        raise NotAllowed(400, "Pick two reports from the same division.")
    if ia.id == ib.id:
        raise NotAllowed(400, "Pick two different reports.")
    view = await asyncio.to_thread(pair_view, store, ia, ib, _home_state(request))
    return _page(request, "analysis_compare.html", me=me, view=view, division=ia.division)
