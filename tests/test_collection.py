import httpx
import pytest

from app.collection import CollectionFilter
from app.config import Settings
from app.poller import Poller
from app.scraper import parse_scores
from app.sources import LiveSource
from conftest import S19, load

BOARD = parse_scores(load(S19))


def test_empty_filter_keeps_everything():
    f = CollectionFilter.from_strings("", " , ")
    assert not f.active
    assert f.apply(BOARD) is BOARD
    assert f.describe() == "all teams"


def test_location_and_division_are_anded_and_case_insensitive():
    f = CollectionFilter.from_strings("va, md", "open")
    kept = f.apply(BOARD)
    assert kept
    assert {t.location for t in kept} <= {"VA", "MD"}
    assert {t.division for t in kept} == {"Open"}
    expected = [t for t in BOARD if t.location in ("VA", "MD") and t.division == "Open"]
    assert kept == expected


def test_multiword_division():
    kept = CollectionFilter.from_strings(divisions="Middle School").apply(BOARD)
    assert kept and {t.division for t in kept} == {"Middle School"}


def test_places_are_from_the_full_board():
    kept = CollectionFilter.from_strings("VA").apply(BOARD)
    full = {t.team_number: t for t in BOARD}
    assert [t.place_overall for t in kept] == [full[t.team_number].place_overall for t in kept]
    assert kept[0].place_state == 1
    assert kept[-1].place_overall > len(kept)  # national rank, not rank within the filtered list


def test_watched_teams_bypass_the_filter():
    outsider = next(t for t in BOARD if t.location != "VA")
    f = CollectionFilter.from_strings("VA", always_keep=[outsider.team_number])
    kept = f.apply(BOARD)
    assert outsider in kept
    assert all(t.location == "VA" or t is outsider for t in kept)


def test_settings_build_the_filter():
    s = Settings(_env_file=None, collect_locations="VA,DC", collect_divisions="Open, CAP",
                 watch_teams="19-0001")
    f = s.collection_filter
    assert f.locations == {"va", "dc"}
    assert f.divisions == {"open", "cap"}
    assert f.always_keep == {"19-0001"}
    assert f.describe() == "locations VA, DC; divisions Open, CAP"


@pytest.mark.anyio
async def test_poller_keeps_only_collected_teams():
    body = load(S19)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    async with httpx.AsyncClient(transport=transport) as client:
        poller = Poller(LiveSource("http://test", client), 60, CollectionFilter.from_strings("VA", "Open"))
        await poller.poll_once()
    st = poller.state
    assert st.board_size == 1478
    assert 0 < len(st.teams) < 100
    assert all(t.location == "VA" and t.division == "Open" for t in st.teams)
    assert set(st.by_number) == {t.team_number for t in st.teams}
