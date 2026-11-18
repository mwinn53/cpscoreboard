import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from conftest import FIXTURES


def make_client(**overrides):
    settings = Settings(_env_file=None, scrape_mode="replay", capture_set=str(FIXTURES),
                        replay_speed=1000, watch_teams="17-0224, 99-9999", auth_enabled=False,
                        mail_backend="console", **overrides)
    return TestClient(create_app(settings))


def wait_for_teams(client, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = client.get("/api/status").json()
        if health["teams"]:
            return health
        time.sleep(0.05)
    raise AssertionError("poller never loaded the fixture")


def test_health_and_api_from_replay():
    with make_client() as client:
        health = wait_for_teams(client)
        assert client.get("/healthz").json() == {"status": "ok"}
        assert health["mode"] == "replay"
        data = client.get("/api/scores").json()
        assert data["teams"][0]["place_overall"] == 1
        assert "raw" not in data["teams"][0]


def test_history_endpoint_and_database_counts():
    with make_client() as client:
        health = wait_for_teams(client)
        assert health["database"]["board_updates"] >= 1
        team = client.get("/api/scores").json()["teams"][0]["team_number"]
        hist = client.get(f"/api/teams/{team}/history").json()
        assert hist["team_number"] == team and len(hist["snapshots"]) >= 1
        assert "observed_at" in hist["snapshots"][0]
        assert client.get("/api/teams/00-0000/history").status_code == 404


def test_dashboard_renders_watchlist_and_filters():
    with make_client() as client:
        wait_for_teams(client)
        # The first fixture (season 17) is loaded; the replay then waits ~0 s and loads season 19.
        page = client.get("/").text
        assert "Watchlist" in page and "99-9999" in page  # missing team listed
        assert 'class="board watch-table"' in page  # board.js opens these rows by default

        partial = client.get("/partials/board", params={"state": "OR", "limit": 5}).text
        assert "<html" not in partial
        assert partial.count('<td class="team">') <= 5 + 1  # 5 rows + watched team

        none = client.get("/partials/board", params={"q": "no-such-team"}).text
        assert "No teams match" in none
        everything = client.get("/partials/board", params={"division": "all", "state": "all"}).text
        assert "showing 100 of" in everything                  # unfiltered: the top 100 unless asked
        assert "showing 100 of" not in client.get("/partials/board", params={"division": "all", "state": "all",
                                                                           "limit": 0}).text


def test_cisco_scores_flag_the_board_and_show_on_the_team_page():
    with make_client() as client:
        wait_for_teams(client)
        deadline = time.monotonic() + 5  # the replay loads season 17, then season 19: edit the final board
        while not client.app.state.poller.state.teams[0].team_number.startswith("19-"):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        team = client.app.state.poller.state.teams[0]
        team.raw.update({"score_1": "10.00", "score_2": "4.50"})
        for t in client.app.state.poller.full_board:  # the team page reads the full board
            if t.team_number == team.team_number:
                t.raw.update(team.raw)
        assert (team.cisco_quiz, team.cisco_pt) == (10.0, 4.5)
        partial = client.get("/partials/board").text
        assert 'class="cisco"' in partial and "Packet Tracer 4.5" in partial
        assert "Adjusted total" not in partial and ">Adj<" not in partial
        assert "C</span> = Cisco Points Scored" in client.get("/").text
        page = client.get(f"/teams/{team.team_number}").text
        assert "Cisco Quiz" in page and "Cisco Packet Tracer" in page


def test_static_files_are_versioned_and_cached_for_a_year():
    import re
    with make_client() as client:
        page = client.get("/").text
        assert "unpkg.com" not in page
        css = re.search(r'href="(/static/style\.css\?v=[0-9a-f]{10})"', page).group(1)
        js = re.search(r'src="(/static/htmx\.min\.js\?v=[0-9a-f]{10})"', page).group(1)
        for url in (css, js):
            r = client.get(url)
            assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert "immutable" not in client.get("/static/style.css").headers.get("cache-control", "")  # unversioned
        assert client.get("/brand/left").headers["cache-control"] == "public, max-age=86400"       # placeholder
