"""Admin page for the server itself: public-scoreboard health, and shutting down.

Shutting down takes a final snapshot of the data volume, then stops the instance
(app/server_control.py). The stop runs after the confirmation page has been sent.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask

from .auth import _page, require_admin, same_origin
from .devices import Device

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/server")


def _render(request: Request, admin: Device, status_code: int = 200, **ctx) -> HTMLResponse:
    monitor, control = request.app.state.monitor, request.app.state.server_control
    return _page(request, "admin_server.html", status_code, me=admin,
                 status=monitor.status() if monitor else None, control=control,
                 notify=request.app.state.settings.admin_notify_email,
                 grace_hours=request.app.state.settings.outage_grace_hours,
                 alert_hours=request.app.state.settings.outage_alert_hours,
                 notice=request.query_params.get("notice"), **ctx)


@router.get("", response_class=HTMLResponse)
async def server_page(request: Request, admin: Device = Depends(require_admin)):
    return _render(request, admin)


@router.post("/competition-start", dependencies=[Depends(same_origin)])
async def competition_start(request: Request, start: str = Form(""), admin: Device = Depends(require_admin)):
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
    return RedirectResponse("/admin/server?notice=Saved+the+competition+start.", status_code=303)


@router.post("/shutdown", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def shutdown(request: Request, confirm: str = Form(""), admin: Device = Depends(require_admin)):
    control = request.app.state.server_control
    if not control.available:
        return _render(request, admin, 400, error="Shutting down isn't available here (not running on AWS).")
    if confirm.strip().upper() != "SHUT DOWN":
        return _render(request, admin, 400, error="Type SHUT DOWN to confirm.")
    log.warning("Admin device %d (%s) requested a shutdown", admin.id, admin.email)
    await asyncio.to_thread(request.app.state.store.checkpoint)
    try:
        snapshot_id = await asyncio.to_thread(control.snapshot)
    except Exception as e:
        log.exception("Snapshot before shutdown failed")
        return _render(request, admin, 502, error=f"The snapshot failed, so the server was not stopped: {e}")
    page = _page(request, "message.html", title="Shutting down",
                 message=(f"Snapshot {snapshot_id} of the data volume has started, and the server is stopping now. "
                          f"This site will be unavailable in a minute. To bring it back later: "
                          f"aws ec2 start-instances --region {control.region} --instance-ids {control.instance_id}"))
    page.background = BackgroundTask(control.stop)  # after the page is sent
    return page
