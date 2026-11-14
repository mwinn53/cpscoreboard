"""Per-image detail for watched teams (#19)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from app.store import SnapshotStore
from app.team_detail import DetailPoller, DetailStore, ReplayDetail, detail_url, parse_images

FIXTURE = Path(__file__).parent / "fixtures" / "images_s19_2026-11-14.json"


def test_parse_real_response():
    images = parse_images(FIXTURE.read_bytes())
    assert len(images) == 3 and [i.image for i in images] == sorted(i.image for i in images)
    server = next(i for i in images if i.image.startswith("Server2022"))
    assert (server.found, server.remaining, server.penalties, server.ccs_score, server.code) == (15, 8, 0, 70, "T")
    assert server.duration == 3 * 3600 + 44 * 60 + 20


def test_detail_url():
    assert detail_url("https://x.org/api/team/scores.php") == "https://x.org/api/image/scores.php"


class FakeSource:
    description = "fake"

    def __init__(self, body):
        self.body, self.calls = body, []

    async def fetch(self, team):
        self.calls.append(team)
        return self.body


def test_fetches_only_watched_teams_that_are_playing_and_stores_changes_only():
    store = SnapshotStore("sqlite://")
    play = {"19-1": 100, "19-2": None}  # 19-2 isn't on the board
    src = FakeSource(FIXTURE.read_bytes())
    detail = DetailPoller(src, DetailStore(store), 300, watched=lambda: ["19-1", "19-2"], play_time=play.get)
    assert asyncio.run(detail.poll_once()) == 3
    assert src.calls == ["19-1"]
    assert asyncio.run(detail.poll_once()) == 0 and src.calls == ["19-1"]  # play time hasn't moved
    play["19-1"] = 400
    assert asyncio.run(detail.poll_once()) == 0 and len(src.calls) == 2  # fetched, nothing changed
    assert len(detail.store.history("19-1")) == 3
    src.body = src.body.replace(b'"found":15', b'"found":16').replace(b'"ccs_score":70', b'"ccs_score":75')
    play["19-1"] = 700
    assert asyncio.run(detail.poll_once()) == 1
    hist = detail.store.history("19-1")
    assert len(hist) == 4 and hist[-1].image.ccs_score == 75

    again = DetailPoller(src, DetailStore(store), 300, watched=lambda: ["19-1"], play_time=play.get)
    again.restore()  # after a restart, unchanged images aren't stored again
    assert asyncio.run(again.poll_once()) == 0 and "19-1" in again.latest
    store.close()


def test_replay_serves_the_newest_saved_response(tmp_path):
    folder = tmp_path / "images" / "19-1"
    folder.mkdir(parents=True)
    (folder / "20261114T100000Z.json").write_bytes(b'{"data": []}')
    (folder / "20261114T110000Z.json").write_bytes(FIXTURE.read_bytes())
    src = ReplayDetail(tmp_path / "images")
    assert len(parse_images(asyncio.run(src.fetch("19-1")))) == 3
    assert asyncio.run(src.fetch("19-9")) is None


def test_team_page_shows_images(site):  # noqa: F811
    from test_auth import make_admin
    admin = make_admin(site)
    app = admin.app
    team = app.state.poller.state.teams[0].team_number
    store = DetailStore(app.state.store)
    detail = DetailPoller(FakeSource(FIXTURE.read_bytes()), store, 300, watched=lambda: [team],
                          play_time=lambda n: 1)
    asyncio.run(detail.poll_once())
    app.state.detail = detail
    page = admin.get(f"/teams/{team}")
    assert page.status_code == 200 and "Server2022_cp19_r2_hs" in page.text
    data = admin.get(f"/api/teams/{team}/images").json()
    assert len(data["images"]) == 3 and len(data["history"]) == 3
    assert admin.get("/api/teams/00-0000/images").status_code == 404


from test_auth import site  # noqa: E402,F401 (fixture)
