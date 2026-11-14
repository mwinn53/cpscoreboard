"""Board settings (M3b): watchlist, aliases, collection filter, legacy import."""

import time
from pathlib import Path

import pytest

from app.board_config import BoardConfig
from app.collection import CollectionFilter
from app.store import SnapshotStore
from test_auth import make_admin, register, site  # noqa: F401 (fixture)
from test_store import ScriptedSource, board, team

LEGACY = Path(__file__).parent.parent / "legacy" / "cpscoreboard"


@pytest.fixture
def store(tmp_path):
    s = SnapshotStore(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    yield s
    s.close()


def test_env_values_seed_the_database_only_once(store):
    first = BoardConfig(store)
    first.seed(["19-1515", "bogus"], "GA", "Middle School")
    assert first.watchlist == ["19-1515"]  # the bad number is skipped with a warning
    assert first.locations == ("GA",) and first.divisions == ("Middle School",)

    first.remove_watch("19-1515")
    first.set_filter(["VA", "md"], [])

    again = BoardConfig(store)  # a restart with the same env vars
    again.seed(["19-1515"], "GA", "Middle School")
    assert again.watchlist == []
    assert again.locations == ("VA", "md") and again.divisions == ()
    f = again.collection_filter()
    assert f.locations == {"va", "md"} and not f.divisions


def test_watchlist_validation_order_and_duplicates(store):
    cfg = BoardConfig(store)
    assert cfg.add_watch(" 19-0002 ") and cfg.add_watch("19-0001")
    assert not cfg.add_watch("19-0002")
    with pytest.raises(ValueError, match="isn't a team number"):
        cfg.add_watch("1515")
    assert BoardConfig(store).watchlist == ["19-0002", "19-0001"]
    assert "19-0001" in cfg.collection_filter().always_keep


def test_aliases_set_change_and_clear(store):
    cfg = BoardConfig(store)
    assert cfg.set_alias("19-0001", "  Cyber   Knights ")
    assert not cfg.set_alias("19-0001", "Cyber Knights")
    assert cfg.set_alias("19-0001", "Knights")
    assert BoardConfig(store).aliases == {"19-0001": "Knights"}
    assert cfg.set_alias("19-0001", "")
    assert BoardConfig(store).aliases == {}


def test_legacy_import_is_idempotent(store):
    team_text = (LEGACY / "tests" / "team").read_text()
    lookups_text = (LEGACY / "tests" / "lookups").read_text()
    cfg = BoardConfig(store)
    result = cfg.import_legacy(team_text, lookups_text + "\nnot-a-team,Oops\n")
    assert result.watch_added == 4 and result.aliases_added == 26 and result.skipped == ("not-a-team",)
    assert cfg.watchlist == ["12-1306", "12-1307", "12-1308", "12-1309"]
    assert cfg.alias("12-1307") == "Dark_Knights.exe"

    again = cfg.import_legacy(team_text, lookups_text)
    assert (again.watch_added, again.aliases_added, again.aliases_changed) == (0, 0, 0)


def test_legacy_runs_files_import(store):
    """runs/lookups lists 17-3226 twice; the first alias wins."""
    cfg = BoardConfig(store)
    cfg.import_legacy((LEGACY / "runs" / "team").read_text(), (LEGACY / "runs" / "lookups").read_text())
    assert cfg.watchlist == ["17-1250", "17-1252", "17-1253"]
    assert cfg.alias("17-3226") == "LMS" and cfg.alias("17-0132") == "RMS"


@pytest.mark.anyio
async def test_reconfigure_applies_at_once_and_stores_newly_collected_teams(store):
    from app.poller import Poller
    body = board(team("19-0001", 100), team("19-0005", 50, state="VA"))
    poller = Poller(ScriptedSource([body, body]), 60, CollectionFilter.from_strings("GA"), store=store)
    await poller.poll_once()
    assert [t.team_number for t in poller.state.teams] == ["19-0001"]
    assert store.counts()["team_snapshots"] == 1

    await poller.reconfigure(CollectionFilter.from_strings("GA", always_keep=["19-0005"]))
    assert [t.team_number for t in poller.state.teams] == ["19-0001", "19-0005"]  # shown immediately

    await poller.poll_once()  # same scoreboard body, but reprocessed so the new team is stored
    assert store.counts()["team_snapshots"] == 2


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- Admin page ---

def test_board_settings_page_requires_admin(site):  # noqa: F811
    viewer = site()
    register(viewer, site.mailer, "coach@example.com")
    assert viewer.get("/admin/board").status_code in (303, 403)
    assert viewer.post("/admin/board/watch", data={"team": "19-0001"},
                       headers={"Origin": "http://testserver"}).status_code in (303, 403)


def test_admin_edits_watchlist_aliases_and_filter(site):  # noqa: F811
    admin = make_admin(site)
    deadline = time.monotonic() + 10  # let the replay reach its last board, so teams stay put
    while not admin.get("/api/status").json()["finished"] and time.monotonic() < deadline:
        time.sleep(0.05)
    page = admin.get("/admin/board")
    assert page.status_code == 200 and "Board settings" in page.text

    r = admin.post("/admin/board/watch", data={"team": "17-0224"})
    assert r.status_code == 303 and "Watching" in admin.get(r.headers["location"]).text
    assert admin.post("/admin/board/watch", data={"team": "nope"}).status_code == 400

    number = admin.get("/api/scores").json()["teams"][0]["team_number"]
    admin.post("/admin/board/alias", data={"team": number, "alias": "Home Team"})
    scores = {t["team_number"]: t for t in admin.get("/api/scores").json()["teams"]}
    assert scores[number]["alias"] == "Home Team"
    board_html = admin.get("/partials/board", params={"q": "home team"}).text
    assert "Home Team" in board_html

    r = admin.post("/admin/board/filter", data={"locations": ["GA"], "divisions": ["Middle School"]})
    assert r.status_code == 303
    status = admin.get("/api/status").json()
    assert "GA" in status["collecting"] and "Middle School" in status["collecting"]

    r = admin.post("/admin/board/import", data={"team_file": "# c\n19-1515\n", "lookups_file": "19-1515,Us"})
    assert "1 watched teams added" in admin.get(r.headers["location"]).text
    assert "19-1515" in admin.get("/").text


def test_board_posts_need_same_origin(site):  # noqa: F811
    admin = make_admin(site)
    r = admin.post("/admin/board/watch", data={"team": "19-0001"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
