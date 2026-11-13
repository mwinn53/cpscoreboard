import json
from datetime import UTC, datetime, timedelta

import pytest

from app.collection import CollectionFilter
from app.config import Settings
from app.poller import Poller
from app.scraper import parse_scores
from app.sources import Fetch, Source
from app.store import SnapshotStore
from conftest import S19, load

pytestmark = pytest.mark.anyio

T0 = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)


def team(number, score, play="01:00:00", state="GA", division="Middle School", **extra):
    return {"team_number": number, "ccs_score": str(score), "play_time": play, "score_time": play,
            "location": state, "division": division, "images": 3, "code": "", **extra}


def board(*rows) -> bytes:
    return json.dumps({"data": list(rows)}).encode()


class ScriptedSource(Source):
    """Returns the given bodies in order, one minute apart."""

    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.n = 0
        self.description = "scripted"

    async def fetch(self):
        if self.n >= len(self.bodies):
            return None
        body = self.bodies[self.n]
        self.n += 1
        return Fetch(body, T0 + timedelta(minutes=self.n))


def make_poller(store, *bodies, collect=None):
    return Poller(ScriptedSource(bodies), 60, collect or CollectionFilter.from_strings("GA", "Middle School"),
                  store=store)


@pytest.fixture
def store():
    s = SnapshotStore("sqlite://")
    yield s
    s.close()


def test_save_and_restore_round_trip(store):
    teams = parse_scores(load(S19))[:5]
    store.save(T0, 1478, 5, teams)
    store.save(T0 + timedelta(minutes=1), 1478, 5, teams[:1])
    r = store.restore()
    assert set(r.latest) == {t.team_number for t in teams}
    assert r.latest[teams[0].team_number].observed_at == T0 + timedelta(minutes=1)
    assert r.previous[teams[0].team_number].team == teams[0]
    assert teams[1].team_number not in r.previous
    assert r.latest[teams[2].team_number].team == teams[2]  # every field survives
    assert (r.board_size, r.data_as_of) == (1478, T0 + timedelta(minutes=1))
    assert store.counts() == {"board_updates": 2, "team_snapshots": 6}


def test_empty_store_restores_nothing(store):
    r = store.restore()
    assert r.latest == {} and r.board_size == 0 and r.data_as_of is None


async def test_only_changed_teams_are_stored(store):
    poller = make_poller(
        store,
        board(team("19-0001", 100), team("19-0002", 90), team("19-9999", 80, state="VA")),
        # Play time ticks for everyone: board changed, but nothing we track did.
        board(team("19-0001", 100, "01:01:00", score_time="01:00:00"),
              team("19-0002", 90, "01:01:00", score_time="01:00:00"),
              team("19-9999", 80, "01:01:00", state="VA")),
        # 19-0002 scores and passes 19-0001.
        board(team("19-0002", 110, "01:02:00"), team("19-0001", 100, "01:02:00", score_time="01:00:00"),
              team("19-9999", 80, state="VA")),
    )
    assert await poller.poll_once()
    assert store.counts() == {"board_updates": 1, "team_snapshots": 2}  # VA team not collected

    assert await poller.poll_once()
    assert store.counts() == {"board_updates": 2, "team_snapshots": 2}

    assert await poller.poll_once()
    # Both changed: 19-0002 scored, 19-0001 lost a place.
    assert store.counts() == {"board_updates": 3, "team_snapshots": 4}
    up, down = poller.state.changes["19-0002"], poller.state.changes["19-0001"]
    assert (up.score_delta, up.place_delta) == (20, 1)
    assert (down.score_delta, down.place_delta) == (0, -1)
    assert up.at == T0 + timedelta(minutes=3)

    history = store.history("19-0002")
    assert [s.team.ccs_score for s in history] == [90, 110]
    assert history[0].observed_at < history[1].observed_at


async def test_restart_restores_board_without_duplicating_rows(store):
    a = board(team("19-0001", 100), team("19-0002", 90))
    b = board(team("19-0002", 110, "01:01:00"), team("19-0001", 100, "01:01:00", score_time="01:00:00"))
    first = make_poller(store, a, b)
    await first.poll_once()
    await first.poll_once()
    rows_before = store.counts()["team_snapshots"]

    second = make_poller(store, b)  # "restarted": same data still on the board
    second.restore()
    st = second.state
    assert st.restored
    assert [t.team_number for t in st.teams] == ["19-0002", "19-0001"]
    assert st.board_size == 2 and st.data_as_of == T0 + timedelta(minutes=2)
    assert st.changes["19-0002"].score_delta == 20

    await second.poll_once()
    assert store.counts()["team_snapshots"] == rows_before
    assert not second.state.restored


async def test_restore_applies_the_current_filter(store):
    await make_poller(store, board(team("19-0001", 100), team("19-0005", 50, state="VA")),
                      collect=CollectionFilter()).poll_once()
    p = make_poller(store)  # GA / Middle School
    p.restore()
    assert [t.team_number for t in p.state.teams] == ["19-0001"]


async def test_failed_write_is_retried_on_the_next_poll(store, monkeypatch):
    body = board(team("19-0001", 100))
    poller = make_poller(store, body, body)
    real_save = store.save

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store, "save", broken)
    await poller.poll_once()
    assert "database write failed" in poller.state.last_error
    assert len(poller.state.teams) == 1  # still shown

    monkeypatch.setattr(store, "save", real_save)
    await poller.poll_once()  # same body, but retried because the write failed
    assert poller.state.last_error is None
    assert store.counts()["team_snapshots"] == 1


def test_database_url_defaults(tmp_path):
    assert Settings(_env_file=None, data_dir=tmp_path).effective_database_url == \
        f"sqlite:///{(tmp_path / 'cpscoreboard.db').as_posix()}"
    assert Settings(_env_file=None, scrape_mode="replay", capture_set="x").effective_database_url == "sqlite://"
    assert Settings(_env_file=None, database_url="sqlite:///other.db").effective_database_url == "sqlite:///other.db"


def test_file_database_is_created_in_wal_mode(tmp_path):
    s = SnapshotStore(f"sqlite:///{(tmp_path / 'sub' / 'db.sqlite').as_posix()}")
    with s.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    s.close()
    assert (tmp_path / "sub" / "db.sqlite").exists()
