import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from conftest import FIXTURES


def make_client(**overrides):
    settings = Settings(_env_file=None, scrape_mode="replay", capture_set=str(FIXTURES),
                        replay_speed=1000, watch_teams="17-0224, 99-9999", **overrides)
    return TestClient(create_app(settings))


def wait_for_teams(client, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = client.get("/healthz").json()
        if health["teams"]:
            return health
        time.sleep(0.05)
    raise AssertionError("poller never loaded the fixture")


def test_health_and_api_from_replay():
    with make_client() as client:
        health = wait_for_teams(client)
        assert health["status"] == "ok"
        assert health["mode"] == "replay"
        data = client.get("/api/scores").json()
        assert data["teams"][0]["place_overall"] == 1
        assert "raw" not in data["teams"][0]


def test_dashboard_renders_watchlist_and_filters():
    with make_client() as client:
        wait_for_teams(client)
        # The first fixture (season 17) is loaded; the replay then waits ~0 s and loads season 19.
        page = client.get("/").text
        assert "Watchlist" in page and "99-9999" in page  # missing team listed

        partial = client.get("/partials/board", params={"state": "OR", "limit": 5}).text
        assert "<html" not in partial
        assert partial.count('<td class="team">') <= 5 + 1  # 5 rows + watched team

        none = client.get("/partials/board", params={"q": "no-such-team"}).text
        assert "No teams match" in none
