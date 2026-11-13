import gzip
import shutil
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.poller import Poller
from app.sources import CaptureSource, LiveSource, ReplaySource
from conftest import S17, S19, load

pytestmark = pytest.mark.anyio


def mock_client(bodies):
    """Client that returns each body in turn; an int means respond with that status."""
    it = iter(bodies)

    def handler(request):
        body = next(it)
        if isinstance(body, int):
            return httpx.Response(body)
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_capture_saves_only_changed_responses(tmp_path):
    a, b = b'{"data": []}', load(S19)
    async with mock_client([a, a, b, b, a]) as client:
        src = CaptureSource(LiveSource("http://test/scores", client), tmp_path / "session")
        for _ in range(5):
            await src.fetch()
    files = sorted((tmp_path / "session").iterdir())
    assert src.saved == 3  # a, b, a
    assert all(f.name.endswith(".json.gz") for f in files)
    assert not any(f.name.endswith(".tmp") for f in files)
    with gzip.open(files[0]) as f:
        assert f.read() in (a, b)


def write_capture(directory, name, body):
    directory.mkdir(parents=True, exist_ok=True)
    with gzip.open(directory / name, "wb") as f:
        f.write(body)


async def test_replay_order_timestamps_and_speed(tmp_path):
    write_capture(tmp_path, "20261113T150200Z.json.gz", b'{"data": [2]}')
    write_capture(tmp_path, "20261113T150000Z.json.gz", b'{"data": [1]}')
    write_capture(tmp_path, "20261113T151000Z.json.gz", b'{"data": [3]}')
    src = ReplaySource(tmp_path, speed=10, default_gap=60)

    f1 = await src.fetch()
    assert f1.body == b'{"data": [1]}'
    assert f1.fetched_at == datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
    assert src.next_delay(999) == 12  # 120 s gap at 10x
    await src.fetch()
    assert src.next_delay(999) == 48  # 480 s gap at 10x
    await src.fetch()
    assert src.next_delay(999) == 6   # default gap after the last capture
    assert await src.fetch() is None
    assert src.position == (3, 3)


async def test_replay_loop_and_plain_json(tmp_path):
    shutil.copy(S19, tmp_path / "a.json.gz")
    (tmp_path / "b.json").write_bytes(b'{"data": []}')
    src = ReplaySource(tmp_path, loop=True)
    bodies = [(await src.fetch()).body for _ in range(3)]
    assert bodies == [load(S19), b'{"data": []}', load(S19)]


def test_replay_requires_captures(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReplaySource(tmp_path)
    with pytest.raises(FileNotFoundError):
        ReplaySource(tmp_path / "missing")


async def test_poller_parses_only_on_change_and_backs_off():
    s17, s19 = load(S17), load(S19)
    async with mock_client([s19, s19, 503, b"<html>maintenance</html>", s17]) as client:
        poller = Poller(LiveSource("http://test/scores", client), interval=60)

        assert await poller.poll_once() is True
        assert len(poller.state.teams) == 1478 and poller.state.changes_seen == 1

        assert await poller.poll_once() is False  # unchanged
        assert poller.state.changes_seen == 1 and poller.state.polls == 2
        assert poller.next_delay() == 60

        assert await poller.poll_once() is False  # HTTP 503
        assert "503" in poller.state.last_error
        assert poller.next_delay() == 120
        assert len(poller.state.teams) == 1478  # last good board kept

        assert await poller.poll_once() is False  # HTML instead of JSON
        assert poller.next_delay() == 240

        assert await poller.poll_once() is True
        assert len(poller.state.teams) == 3432
        assert poller.state.last_error is None and poller.next_delay() == 60


def test_backoff_is_capped():
    poller = Poller(ReplaySource.__new__(ReplaySource), interval=60)
    poller._failures = 20
    assert poller.next_delay() == Poller.MAX_BACKOFF


def test_prod_only_allows_live_mode():
    with pytest.raises(ValidationError):
        Settings(app_env="prod", scrape_mode="capture")
    with pytest.raises(ValidationError):
        Settings(app_env="prod", scrape_mode="replay", capture_set="x")
    assert Settings(app_env="prod", scrape_mode="live").scrape_mode == "live"


def test_replay_requires_capture_set():
    with pytest.raises(ValidationError):
        Settings(scrape_mode="replay")
