"""Shared Jinja templates, filters, and per-request context (who's viewing, which environment)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .devices import describe_ua
from .sources import utcnow

RECENT_SECONDS = 300  # scoreboard rows that changed within this window are highlighted


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


_tz = ZoneInfo("America/New_York")


def set_timezone(name: str) -> None:
    """Called by create_app with DISPLAY_TIMEZONE (validated in Settings)."""
    global _tz
    _tz = ZoneInfo(name)


def _local(when: datetime | None, seconds: bool = False) -> str:
    """UTC (aware, or naive as stored) -> e.g. "Nov 14, 2026 10:05 AM EST"."""
    if when is None:
        return ""
    t = (when if when.tzinfo else when.replace(tzinfo=UTC)).astimezone(_tz)
    hour = t.hour % 12 or 12
    clock = f"{hour}:{t.minute:02d}" + (f":{t.second:02d}" if seconds else "")
    return f"{t:%b} {t.day}, {t.year} {clock} {'AM' if t.hour < 12 else 'PM'} {t.tzname()}"


def _date(when: datetime | None) -> str:
    return _local(when)


def _num(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}" if value == int(value) else f"{value:.2f}"


def _signed(value: float) -> str:
    return ("+" if value > 0 else "−") + _num(abs(value))


def _recent(when: datetime | None) -> bool:
    return when is not None and (utcnow() - when).total_seconds() <= RECENT_SECONDS


def _logos(request: Request) -> dict[str, str]:
    """Image URL per header slot; versioned so a new upload isn't served from cache."""
    from .branding import SLOTS
    brand = getattr(request.app.state, "branding", None)
    versions = brand.versions() if brand else {}
    return {slot: f"/brand/{slot}" + (f"?v={v}" if (v := versions.get(slot)) else "") for slot in SLOTS}


def _logo_links(request: Request) -> dict[str, str]:
    from .branding import CYBERPATRIOT_LINK
    board = getattr(request.app.state, "board", None)
    return {"left": CYBERPATRIOT_LINK, "right": board.school_logo_link if board else ""}


def _context(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "app_env": settings.app_env.value,
        "site_title": settings.site_title,
        "scrape_mode": settings.scrape_mode.value,
        "auth_enabled": settings.auth_enabled,
        "viewer": getattr(request.state, "device", None),
        "logos": _logos(request),
        "logo_links": _logo_links(request),
    }


templates = Jinja2Templates(directory=Path(__file__).parent / "templates", context_processors=[_context])
templates.env.filters.update(hms=_hms, ago=_ago, num=_num, signed=_signed, date=_date, local=_local,
                             browser=describe_ua)
templates.env.tests.update(recent=_recent)
