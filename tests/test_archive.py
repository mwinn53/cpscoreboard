"""Season archive: the full raw board, one file per day."""

import gzip
from datetime import UTC, datetime, timedelta

import pytest

from app.archive import Archive
from app.collection import CollectionFilter
from app.poller import Poller
from app.sources import ReplaySource
from test_auth import make_admin, site  # noqa: F401 (fixture)
from test_store import ScriptedSource, board, team

pytestmark = pytest.mark.anyio


def eastern(y, m, d, hh, mm=0):
    from zoneinfo import ZoneInfo
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)


def test_one_file_per_local_day_keeps_the_latest(tmp_path):
    a = Archive(tmp_path / "archive")
    a.save(b'{"data": [1]}', eastern(2026, 11, 14, 9))
    a.save(b'{"data": [2]}', eastern(2026, 11, 14, 21))
    a.save(b'{"data": [3]}', eastern(2026, 11, 14, 23, 30))  # 04:30 UTC on the 15th: still the 14th locally
    a.save(b'{"data": [4]}', eastern(2026, 11, 15, 8))
    files = a.files()
    assert [str(f.day) for f in files] == ["2026-11-15", "2026-11-14"]
    with gzip.open(a.path(files[1].name)) as f:
        assert f.read() == b'{"data": [3]}'
    assert not list((tmp_path / "archive").glob("*.tmp"))


def test_paths_only_resolve_archive_names(tmp_path):
    a = Archive(tmp_path / "archive")
    a.save(b"{}", datetime(2026, 11, 14, 15, tzinfo=UTC))
    assert a.path("20261114T150000Z.json.gz") is not None
    for bad in ("../secret.json.gz", "cpscoreboard.db", "20261114T150000Z.json.gz.tmp", "20991231T000000Z.json.gz"):
        assert a.path(bad) is None


def test_archive_files_replay_like_captures(tmp_path):
    a = Archive(tmp_path)
    a.save(board(team("19-0001", 100)), datetime(2026, 11, 14, 15, tzinfo=UTC))
    items = ReplaySource(tmp_path, speed=1000).items
    assert len(items) == 1 and items[0][1] == datetime(2026, 11, 14, 15, tzinfo=UTC)  # time read from the name


async def test_poller_archives_the_full_board_not_just_collected_teams(tmp_path):
    a = Archive(tmp_path)
    body = board(team("19-0001", 100), team("19-0005", 50, state="VA"))
    poller = Poller(ScriptedSource([body, body]), 60, CollectionFilter.from_strings("GA"), archive=a)
    await poller.poll_once()
    await poller.poll_once()  # unchanged: not rewritten
    (only,) = a.files()
    with gzip.open(a.path(only.name)) as f:
        assert f.read() == body  # both teams, though only GA is collected


def test_admin_archive_page_and_downloads(site, tmp_path):  # noqa: F811
    admin = make_admin(site)
    assert "Archiving is off here" in admin.get("/admin/archive").text  # the test site replays

    archive = Archive(tmp_path / "archive")
    archive.save(b'{"data": []}', datetime(2026, 11, 14, 15, tzinfo=UTC) - timedelta(days=1))
    admin.app.state.archive = archive
    page = admin.get("/admin/archive").text
    assert "Fri Nov 13, 2026" in page and "/admin/archive/20261113T150000Z.json.gz" in page
    r = admin.get("/admin/archive/20261113T150000Z.json.gz")
    assert r.status_code == 200 and gzip.decompress(r.content) == b'{"data": []}'
    assert admin.get("/admin/archive/..%2Fcpscoreboard.db").status_code == 404

    viewer = site()
    assert viewer.get("/admin/archive/20261113T150000Z.json.gz").status_code in (303, 401, 403)
