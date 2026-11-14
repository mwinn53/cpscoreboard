"""Per-image detail for watched teams (#19)."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.store import SnapshotStore
from app.team_detail import (DetailPoller, DetailStore, ReplayDetail, chart_url, detail_url, parse_image_chart,
                              parse_images)

FIXTURE = Path(__file__).parent / "fixtures" / "detail" / "images_s19_2026-11-14.json"


def test_parse_real_response():
    images = parse_images(FIXTURE.read_bytes())
    assert len(images) == 3 and [i.image for i in images] == sorted(i.image for i in images)
    server = next(i for i in images if i.image.startswith("Server2022"))
    assert (server.found, server.remaining, server.penalties, server.ccs_score, server.code) == (15, 8, 0, 70, "T")
    assert server.duration == 3 * 3600 + 44 * 60 + 20


def test_detail_url():
    assert detail_url("https://x.org/api/team/scores.php") == "https://x.org/api/image/scores.php"
    assert chart_url("https://x.org/api/team/scores.php") == "https://x.org/api/image/chart.php"


CHART = Path(__file__).parent / "fixtures" / "detail" / "image_chart_s19_2026-11-14.json"


def test_parse_official_image_chart():
    now = datetime(2026, 11, 14, 14, 40, tzinfo=UTC)
    series = parse_image_chart(CHART.read_bytes(), now)
    assert 1 <= len(series) <= 3 and all(n for n, _ in series)
    for _, pts in series:
        assert pts == sorted(pts) and all(now - timedelta(hours=7) < t <= now for t, _ in pts)  # UTC, this year


def test_official_chart_year_rolls_back_in_january():
    body = b'{"cols":[{"label":"Time"},{"label":"Img_x"}],"rows":[{"c":[{"v":"12/31 23:55"},{"v":5}]},' \
           b'{"c":[{"v":"12/31 23:59"},{"v":"null"}]}]}'
    (name, pts), = parse_image_chart(body, datetime(2027, 1, 1, 0, 10, tzinfo=UTC))
    assert name == "Img_x" and pts == [(datetime(2026, 12, 31, 23, 55, tzinfo=UTC), 5.0)]


def test_district_history_ranks_among_district_teams_in_the_division():
    from app.team_view import district_history
    store = SnapshotStore("sqlite://")
    t0 = datetime(2026, 11, 14, 15, tzinfo=UTC)

    def snap(n, place, div="Middle School"):
        from app.scraper import TeamScore
        return TeamScore(team_number=n, team_id=1, location="GA", division=div, tier="", images=3, play_time=1,
                         score_time=1, ccs_score=1, adjustment=None, total=None, code="", place_overall=place,
                         place_division=place, place_state=place, place_state_division=place)

    store.save(t0, 3, 3, [snap("19-0001", 5), snap("19-0002", 9), snap("19-0003", 1, div="Open")])
    store.save(t0 + timedelta(minutes=5), 3, 3, [snap("19-0002", 3)])   # passes 19-0001
    store.save(t0 + timedelta(minutes=9), 3, 3, [snap("19-0003", 2, div="Open")])  # other division: no effect
    hist = district_history(store, "19-0001", {"19-0001", "19-0002", "19-0003"})
    assert hist == [(t0, 1), (t0 + timedelta(minutes=5), 2)]
    store.close()


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


def test_multi_chart_and_sparkline():
    from zoneinfo import ZoneInfo

    from app.charts import multi_step_chart, short_image_name, sparkline
    t = datetime(2026, 11, 14, 15, tzinfo=UTC)
    chart = multi_step_chart([("Win_a", [(t, 5), (t + timedelta(minutes=5), 10)]), ("Srv_b", [(t, 10)])],
                             t + timedelta(minutes=10), tz=ZoneInfo("America/New_York"), label="Images")
    assert 'class="series s1"' in chart.svg and 'class="series s2"' in chart.svg
    assert "Win 5 · Srv 10" in chart.svg.replace("&quot;", '"') or "Win 5" in chart.svg
    assert short_image_name("Windows11_cp19_intro") == "Windows11"
    assert sparkline([(t, 3), (t + timedelta(minutes=5), 1)], t + timedelta(minutes=9), invert=True).startswith("<svg")
    assert sparkline([], t) == ""


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
