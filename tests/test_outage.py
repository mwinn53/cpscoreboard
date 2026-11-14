"""Outage alert (public scoreboard down for a day) and the admin shutdown button."""

from datetime import UTC, datetime, timedelta

import pytest

from app.board_config import BoardConfig
from app.outage import OutageMonitor
from app.store import SnapshotStore
from test_auth import FakeMailer, make_admin, register, site  # noqa: F401 (fixture)

T0 = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)  # competition starts


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def setup():
    store = SnapshotStore("sqlite://")
    clock, mailer = Clock(T0), FakeMailer()
    monitor = OutageMonitor(BoardConfig(store), mailer, "admin@example.com", "Scorebot",
                            "https://scores.example.org", clock=clock)
    yield monitor, clock, mailer
    store.close()


def test_start_is_recorded_from_the_first_board_with_play_time(setup):
    monitor, clock, _ = setup
    monitor.record(True, playing=False)
    assert monitor.status().competition_start is None
    monitor.record(True, playing=True)
    clock.now += timedelta(days=1)
    monitor.record(True, playing=True)  # the first one sticks
    assert monitor.status().competition_start == T0
    assert monitor.status().monitoring_from == T0 + timedelta(hours=72)


def test_no_alert_before_monitoring_starts_or_before_24_hours(setup):
    monitor, clock, mailer = setup
    monitor.record(True, playing=True)
    clock.now = T0 + timedelta(hours=10)
    monitor.record(False)  # down during the grace period...
    clock.now = T0 + timedelta(hours=72 + 23)
    assert not monitor.record(False)  # ...counts only from hour 72
    clock.now = T0 + timedelta(hours=72 + 24)
    assert monitor.record(False)
    to, subject, body = mailer.sent[-1]
    assert to == "admin@example.com" and "down for 24 hours" in subject
    assert "https://scores.example.org/admin/server" in body and "https://scores.example.org/admin/archive" in body
    assert "shut down the server" in body

    clock.now += timedelta(hours=5)
    assert not monitor.record(False)  # once per outage
    assert monitor.status().alerted


def test_recovery_resets_and_a_new_outage_alerts_again(setup):
    monitor, clock, mailer = setup
    monitor.record(True, playing=True)
    clock.now = T0 + timedelta(days=5)
    monitor.record(False)
    clock.now += timedelta(hours=12)
    monitor.record(True)  # back before 24 h: no alert
    assert monitor.status().down_since is None and not mailer.sent

    monitor.record(False)
    clock.now += timedelta(hours=24)
    assert monitor.record(False) and len(mailer.sent) == 1


def test_no_alert_without_a_competition_start(setup):
    monitor, clock, mailer = setup
    monitor.record(False)
    clock.now += timedelta(days=10)
    assert not monitor.record(False) and not mailer.sent


def test_outage_state_survives_a_restart():
    store = SnapshotStore("sqlite://")
    clock = Clock(T0)
    first = OutageMonitor(BoardConfig(store), FakeMailer(), "a@example.com", "S", clock=clock)
    first.record(True, playing=True)
    clock.now = T0 + timedelta(hours=80)
    first.record(False)
    mailer = FakeMailer()
    second = OutageMonitor(BoardConfig(store), mailer, "a@example.com", "S", clock=clock)  # restart
    clock.now = T0 + timedelta(hours=104)
    assert second.record(False) and mailer.sent
    store.close()


@pytest.mark.anyio
async def test_poller_reports_failures_and_successes(setup):
    from app.poller import Poller
    from test_store import ScriptedSource, board, team
    monitor, clock, _ = setup

    class Flaky(ScriptedSource):
        async def fetch(self):
            if self.n == 1:
                self.n += 1
                raise OSError("connection refused")
            return await super().fetch()

    body = board(team("19-0001", 100, play="01:00:00"))
    poller = Poller(Flaky([body, None, body, b"<html>gone</html>"]), 60, monitor=monitor)  # [1] is the failure
    await poller.poll_once()
    assert monitor.status().competition_start == T0 and monitor.status().down_since is None
    await poller.poll_once()  # connection refused
    assert monitor.status().down_since == T0
    await poller.poll_once()  # same board again: back up
    assert monitor.status().down_since is None
    await poller.poll_once()  # an HTML page instead of the API
    assert monitor.status().down_since == T0


class FakeControl:
    region, instance_id, available = "us-east-1", "i-123", True

    def __init__(self):
        self.calls = []

    def snapshot(self):
        self.calls.append("snapshot")
        return "snap-abc"

    def stop(self):
        self.calls.append("stop")


def test_admin_server_page_and_shutdown(site):  # noqa: F811
    admin = make_admin(site)
    page = admin.get("/admin/server")
    assert page.status_code == 200 and "Not available here" in page.text  # no AWS ids in tests
    assert admin.post("/admin/server/shutdown", data={"confirm": "SHUT DOWN"}).status_code == 400

    control = FakeControl()
    admin.app.state.server_control = control
    r = admin.post("/admin/server/shutdown", data={"confirm": "yes"})
    assert r.status_code == 400 and "Type SHUT DOWN" in r.text and not control.calls
    r = admin.post("/admin/server/shutdown", data={"confirm": "shut down"})
    assert r.status_code == 200 and "snap-abc" in r.text and "start-instances" in r.text
    assert control.calls == ["snapshot", "stop"]  # stop runs after the page is sent


def test_shutdown_is_admin_only_and_same_origin(site):  # noqa: F811
    viewer = site()
    register(viewer, site.mailer, "coach@example.com")
    viewer.app.state.server_control = control = FakeControl()
    assert viewer.post("/admin/server/shutdown", data={"confirm": "SHUT DOWN"}).status_code in (303, 403)
    admin = make_admin(site)
    admin.app.state.server_control = control
    r = admin.post("/admin/server/shutdown", data={"confirm": "SHUT DOWN"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and not control.calls
