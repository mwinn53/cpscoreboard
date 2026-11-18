"""Editable scoreboard address (#51)."""

import asyncio
import gzip
from pathlib import Path

import httpx

from app import scoreboard_url
from app.board_config import BoardConfig
from app.sources import CaptureSource, LiveSource
from app.store import SnapshotStore
from app.team_detail import DetailPoller, LiveDetail, OfficialDetailClient
from test_auth import make_admin, site  # noqa: F401 (fixture)

BOARD = gzip.decompress((Path(__file__).parent / "fixtures" / "scores_s19_2026-11-13.json.gz").read_bytes())
NEW = "https://mirror.example.org/api/team/scores.php"


def mock_client(routes):
    def handler(request):
        status, body = routes.get(str(request.url), (404, b"nope"))
        return httpx.Response(status, content=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_check_format():
    assert scoreboard_url.check_format(NEW) is None
    assert scoreboard_url.check_format("ftp://x.org/a") and scoreboard_url.check_format("not a url")
    assert scoreboard_url.check_format("") and scoreboard_url.check_format("https://" + "a" * 600)


def test_test_fetch():
    async def go(url):
        async with mock_client({NEW: (200, BOARD), "https://bad.example.org/": (200, b"<html>"),
                                "https://down.example.org/": (503, b"")}) as c:
            return await scoreboard_url.test(c, url)
    ok = asyncio.run(go(NEW))
    assert ok.ok and ok.teams > 1000
    assert not asyncio.run(go("https://bad.example.org/")).ok
    assert "503" in asyncio.run(go("https://down.example.org/")).error


def test_apply_switches_every_live_fetcher():
    class State:
        pass

    class Poller:
        pass

    state, client = State(), httpx.AsyncClient()
    state.poller = Poller()
    state.poller.source = CaptureSource(LiveSource("https://old.org/api/team/scores.php", client), Path("x"))
    state.detail = DetailPoller(LiveDetail("https://old.org/api/image/scores.php", client), None, 300,
                                watched=list, play_time=lambda n: None)
    state.official = OfficialDetailClient(client, "https://old.org/api/team/scores.php")
    scoreboard_url.apply(state, NEW)
    assert state.poller.source.inner.url == NEW and NEW in state.poller.source.description
    assert state.detail.source.url == "https://mirror.example.org/api/image/scores.php"
    assert state.official.chart_url == "https://mirror.example.org/api/image/chart.php"
    asyncio.run(client.aclose())


def test_effective_prefers_the_saved_address():
    store = SnapshotStore("sqlite://")
    board = BoardConfig(store)
    assert scoreboard_url.effective(board, "https://default.org/") == "https://default.org/"
    board.set_value(scoreboard_url.KEY, NEW)
    assert scoreboard_url.effective(board, "https://default.org/") == NEW
    store.close()


def test_configuration_page_saves_only_after_a_good_test(site):  # noqa: F811
    admin = make_admin(site)
    app = admin.app
    app.state.http = mock_client({NEW: (200, BOARD)})
    page = admin.get("/admin/config").text
    assert 'id="scoreboard"' in page and "info.js" in page and page.count('class="info-btn"') >= 6
    assert admin.post("/admin/config/scoreboard-url", data={"url": "nope"}).status_code == 400
    r = admin.post("/admin/config/scoreboard-url", data={"url": "https://elsewhere.example.org/scores"})
    assert r.status_code == 400 and "Not saved" in r.text
    assert app.state.board.get_value(scoreboard_url.KEY) == ""
    r = admin.post("/admin/config/scoreboard-url", data={"url": NEW})
    assert r.status_code == 303 and "teams" in r.headers["location"]
    assert app.state.board.get_value(scoreboard_url.KEY) == NEW
    page = admin.get("/admin/config").text
    assert f'value="{NEW}"' in page and "Reset to default" in page
    assert admin.post("/admin/config/scoreboard-url", data={"reset": "1"}).status_code == 303
    assert app.state.board.get_value(scoreboard_url.KEY) == ""


def test_variable_interval_backs_off_while_quiet_and_resets_on_a_change():
    from app.poller import Poller
    from app.sources import Source

    class Fixed(Source):
        description = "fixed"

        async def fetch(self):
            return None
    p = Poller(Fixed(), 60)
    p.configure(60, True)
    assert p.current_interval() == 60
    p.quiet = 3
    assert p.current_interval() == 120 and p.next_delay() == 120
    p.quiet = 9
    assert p.current_interval() == 480
    p.quiet = 30
    assert p.current_interval() == 600            # capped
    p.configure(60, False)
    p.quiet = 30
    assert p.current_interval() == 60             # fixed interval ignores quiet polls


def test_update_interval_on_the_config_page(site):  # noqa: F811
    admin = make_admin(site)
    page = admin.get("/admin/config").text
    assert "Update interval" in page and "Variable interval" in page and "Per-image detail" not in page
    assert admin.post("/admin/config/polling", data={"interval": "90", "variable": "1"}).status_code == 303
    poller = admin.app.state.poller
    assert (poller.interval, poller.variable) == (90, True)
    assert admin.app.state.board.get_value("poll_interval") == "90"
    assert admin.post("/admin/config/polling", data={"interval": "5"}).status_code == 303
    assert (poller.interval, poller.variable) == (15, False)      # clamped; unchecked = fixed


def test_variable_interval_grows_to_30_minutes_after_6_quiet_hours():
    from datetime import timedelta

    from app.poller import Poller
    from app.sources import Source, utcnow

    class Fixed(Source):
        description = "fixed"

        async def fetch(self):
            return None
    p = Poller(Fixed(), 60)
    p.configure(60, True)
    p.quiet = 30
    assert p.current_interval() == 600                       # quiet, but not for long
    p.quiet_since = utcnow() - timedelta(hours=6, minutes=1)
    assert p.current_interval() == 1800                      # between rounds
    p.quiet = 100000
    assert p.current_interval() == 1800                      # no overflow however long it stays quiet
