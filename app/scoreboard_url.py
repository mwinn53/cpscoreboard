"""The scoreboard's address, editable on /admin/config (issue #51).

``SCOREBOARD_URL`` is the default; an admin can override it, saved in ``app_settings``.
A new address is only saved after a test fetch returns a readable board. It takes
effect at once: the poller's live source, the per-image detail poller and the team
page's on-demand fetches all switch (the per-image endpoints share the same base,
``.../api/image/...`` next to ``.../api/team/scores.php``). Replay mode has no live
source, so the setting is shown but has no effect there.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .board_config import BoardConfig
from .scraper import ScoreboardFormatError, parse_scores
from .sources import CaptureSource, LiveSource
from .team_detail import CaptureDetail, LiveDetail, chart_url, detail_url

log = logging.getLogger(__name__)

KEY = "scoreboard_url"
MAX_LENGTH = 500


def effective(board: BoardConfig, default: str) -> str:
    return board.get_value(KEY) or default


def check_format(url: str) -> str | None:
    """An error message, or None if the address looks usable."""
    if not url or len(url) > MAX_LENGTH:
        return "Enter the scoreboard's full address."
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "The address must start with https:// (or http://)."
    return None


@dataclass(frozen=True)
class TestResult:
    ok: bool
    teams: int = 0
    error: str = ""


async def test(client: httpx.AsyncClient, url: str) -> TestResult:
    """Fetch the address once and check it returns a scoreboard."""
    try:
        resp = await client.get(url, timeout=20)
        resp.raise_for_status()
        teams = parse_scores(resp.content)
    except httpx.HTTPStatusError as e:
        return TestResult(False, error=f"it answered HTTP {e.response.status_code}")
    except httpx.HTTPError as e:
        return TestResult(False, error=f"it couldn't be reached ({e.__class__.__name__})")
    except ScoreboardFormatError as e:
        return TestResult(False, error=f"it didn't return a scoreboard ({e})")
    return TestResult(True, teams=len(teams))


def apply(state, url: str) -> None:
    """Point every live fetcher at ``url`` (no-op parts in replay mode)."""
    source = getattr(state.poller, "source", None)
    live = source.inner if isinstance(source, CaptureSource) else source
    if isinstance(live, LiveSource):
        live.url = url
        live.description = f"live: {url}"
        if isinstance(source, CaptureSource):
            source.description = f"capture → {source.directory} ({live.description})"
    detail = getattr(state, "detail", None)
    dsource = detail.source if detail is not None else None
    dlive = dsource.inner if isinstance(dsource, CaptureDetail) else dsource
    if isinstance(dlive, LiveDetail):
        dlive.url = detail_url(url)
        dlive.description = f"live: {dlive.url}"
    official = getattr(state, "official", None)
    if official is not None:
        official.images_url, official.chart_url = detail_url(url), chart_url(url)
        official._cache.clear()
    log.info("Scoreboard address set to %s", url)
