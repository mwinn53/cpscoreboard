"""Header logos: two square images (left and right of the top bar) the admin uploads.

The admin page crops the image to a square in the browser and sends a PNG, so the
server only checks it's a reasonably small PNG. Images are kept in the database
(they're a few tens of KB) and cached in memory. Until one is uploaded, a
placeholder is shown.
"""

from __future__ import annotations

import base64
import binascii
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import Column, DateTime, LargeBinary, String, Table, delete, insert, select

from .store import SnapshotStore, metadata

SLOTS = {"left": "CyberPatriot logo", "right": "School logo"}
MAX_BYTES = 1_000_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

site_images = Table(
    "site_images", metadata,
    Column("slot", String(16), primary_key=True),
    Column("content_type", String(64), nullable=False),
    Column("data", LargeBinary, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)


@dataclass(frozen=True)
class Image:
    data: bytes
    content_type: str
    updated_at: datetime

    @property
    def version(self) -> str:
        return str(int(self.updated_at.replace(tzinfo=UTC).timestamp()))


def decode_png(data_url: str) -> bytes:
    """``data:image/png;base64,...`` from the cropper -> PNG bytes. Raises ValueError."""
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise ValueError("Choose an image and crop it first.")
    if len(data_url) > MAX_BYTES * 4 // 3 + len(prefix) + 4:
        raise ValueError("That image is too large.")
    try:
        data = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("That image couldn't be read.") from None
    if not data.startswith(PNG_MAGIC) or len(data) > MAX_BYTES:
        raise ValueError("That image couldn't be read.")
    return data


class Branding:
    def __init__(self, store: SnapshotStore):
        self.store = store
        self._mutex = threading.Lock()
        with store.lock, store.engine.connect() as conn:
            rows = conn.execute(select(site_images)).all()
        self._images = {r.slot: Image(r.data, r.content_type, r.updated_at) for r in rows}

    def get(self, slot: str) -> Image | None:
        return self._images.get(slot)

    def versions(self) -> dict[str, str | None]:
        return {slot: (img.version if (img := self._images.get(slot)) else None) for slot in SLOTS}

    def set(self, slot: str, png: bytes) -> None:
        if slot not in SLOTS:
            raise ValueError("Unknown logo.")
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        with self._mutex, self.store.lock, self.store.engine.begin() as conn:
            conn.execute(delete(site_images).where(site_images.c.slot == slot))
            conn.execute(insert(site_images).values(slot=slot, content_type="image/png", data=png, updated_at=now))
            self._images[slot] = Image(png, "image/png", now)

    def clear(self, slot: str) -> None:
        with self._mutex, self.store.lock, self.store.engine.begin() as conn:
            conn.execute(delete(site_images).where(site_images.c.slot == slot))
            self._images.pop(slot, None)


router = APIRouter()


def _placeholder(label: str) -> bytes:
    lines = label.split(" ", 1)
    text = "".join(f'<tspan x="50" dy="{0 if i == 0 else 14}">{w}</tspan>' for i, w in enumerate(lines))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            f'<rect x="2" y="2" width="96" height="96" rx="12" fill="none" stroke="#94a0b0" '
            f'stroke-width="3" stroke-dasharray="8 6"/>'
            f'<text x="50" y="46" text-anchor="middle" font-family="system-ui,sans-serif" font-size="12" '
            f'fill="#94a0b0">{text}</text></svg>').encode()


@router.get("/brand/{slot}")
def brand_image(request: Request, slot: str) -> Response:
    """Public: the logos also appear on the registration pages."""
    if slot not in SLOTS:
        return Response(status_code=404)
    img = request.app.state.branding.get(slot)
    if img is None:
        return Response(_placeholder(SLOTS[slot]), media_type="image/svg+xml",
                        headers={"Cache-Control": "no-cache"})
    # The page links to /brand/<slot>?v=<version>, so a new upload gets a new URL.
    return Response(img.data, media_type=img.content_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
