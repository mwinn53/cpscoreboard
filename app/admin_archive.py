"""Admin page for the season archive: list the daily files and download them."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse

from .auth import NotAllowed, _page, require_admin
from .devices import Device

router = APIRouter(prefix="/admin/archive")


@router.get("", response_class=HTMLResponse)
async def archive_page(request: Request, admin: Device = Depends(require_admin)):
    archive = request.app.state.archive
    files = await asyncio.to_thread(archive.files) if archive else []
    return _page(request, "admin_archive.html", me=admin, enabled=archive is not None, files=files,
                 total=sum(f.size for f in files))


@router.get("/{name}")
async def archive_download(request: Request, name: str, admin: Device = Depends(require_admin)):
    archive = request.app.state.archive
    path = archive.path(name) if archive else None
    if path is None:
        raise NotAllowed(404, "No such archive file.")
    return FileResponse(path, media_type="application/gzip", filename=name)
