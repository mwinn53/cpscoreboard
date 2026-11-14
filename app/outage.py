"""Watch the public scoreboard and email the admin once it's been down for a day.

After the season the public scoreboard is taken down; when that happens the
server has nothing left to collect, so it can be shut down (after downloading the
archive). The rule:

* The competition start is recorded automatically the first time a board shows
  any play time (or the admin sets it on /admin/server).
* Monitoring starts 72 hours after that, so outages during setup don't count.
* "Down" means a poll got no usable board: a fetch error, an unexpected response,
  or an empty board. One good poll ends the outage.
* When the scoreboard has been down for 24 hours (counted from when monitoring
  started, if the outage began earlier), the admin is emailed once per outage, with
  links to download the archive and to shut the server down.

State lives in ``app_settings`` and is written only when it changes, so a restart
mid-outage keeps counting from the original start.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .board_config import BoardConfig
from .mail import Mailer

log = logging.getLogger(__name__)

COMPETITION_START, DOWN_SINCE, ALERTED_FOR = "competition_start", "scoreboard_down_since", "outage_alerted_for"


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value).astimezone(UTC) if value else None
    except ValueError:
        return None


def _iso(when: datetime | None) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds") if when else ""


@dataclass(frozen=True)
class OutageStatus:
    competition_start: datetime | None
    monitoring_from: datetime | None   # competition start + grace
    down_since: datetime | None
    alert_at: datetime | None          # when an alert goes out if the outage continues
    alerted: bool


class OutageMonitor:
    def __init__(self, board: BoardConfig, mailer: Mailer, notify: str | None, site_title: str,
                 public_url: str = "", grace: timedelta = timedelta(hours=72),
                 threshold: timedelta = timedelta(hours=24),
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.board, self.mailer, self.notify = board, mailer, notify
        self.site_title, self.public_url = site_title, public_url.rstrip("/")
        self.grace, self.threshold, self.clock = grace, threshold, clock

    def _get(self, key: str) -> datetime | None:
        return _parse(self.board.get_value(key))

    def status(self) -> OutageStatus:
        start, down = self._get(COMPETITION_START), self._get(DOWN_SINCE)
        monitoring_from = start + self.grace if start else None
        alert_at = None
        if down and monitoring_from:
            alert_at = max(down, monitoring_from) + self.threshold
        alerted = bool(down) and self.board.get_value(ALERTED_FOR) == _iso(down)
        return OutageStatus(start, monitoring_from, down, alert_at, alerted)

    def set_competition_start(self, when: datetime | None) -> None:
        self.board.set_value(COMPETITION_START, _iso(when))

    def record(self, ok: bool, playing: bool = False) -> bool:
        """Note one poll's outcome. Returns True if an alert email was sent."""
        now = self.clock()
        if ok:
            if playing and not self._get(COMPETITION_START):
                self.set_competition_start(now)
                log.info("Competition start recorded: %s (outage alerts can start 72 h later)", _iso(now))
            if self._get(DOWN_SINCE):
                log.info("Public scoreboard is back (was down since %s)", self.board.get_value(DOWN_SINCE))
                self.board.set_value(DOWN_SINCE, "")
            return False

        if not self._get(DOWN_SINCE):
            self.board.set_value(DOWN_SINCE, _iso(now))
            log.warning("Public scoreboard unavailable; outage started %s", _iso(now))
        st = self.status()
        if st.alerted or st.alert_at is None or now < st.alert_at:
            return False
        sent = self._send(st, now)
        if sent:
            self.board.set_value(ALERTED_FOR, _iso(st.down_since))
        return sent

    def _send(self, st: OutageStatus, now: datetime) -> bool:
        if not self.notify:
            log.warning("Scoreboard down for %s, but ADMIN_NOTIFY_EMAIL isn't set; no alert sent", now - st.down_since)
            self.board.set_value(ALERTED_FOR, _iso(st.down_since))  # don't retry every minute
            return False
        hours = int((now - max(st.down_since, st.monitoring_from)).total_seconds() // 3600)
        base = self.public_url
        body = (
            f"The public CyberPatriot scoreboard (https://scoreboard.uscyberpatriot.org/) has been unavailable "
            f"for {hours} hours (down since {_iso(st.down_since)} UTC). It is usually taken down after the "
            f"season ends, so there's likely nothing left to collect.\n\n"
            f"Recommended: shut down the server to stop paying for it.\n\n"
            f"1. Download the season archive (one full scoreboard per day):\n   {base}/admin/archive\n\n"
            f"2. Shut down the server (snapshots the data volume, then stops the instance; open it in the "
            f"browser you use as admin):\n   {base}/admin/server\n\n"
            f"If the scoreboard comes back, nothing happens; you'll get another email if it goes down again.\n")
        try:
            self.mailer.send(self.notify, f"{self.site_title}: the public scoreboard has been down for {hours} hours",
                             body)
        except Exception:
            log.exception("Failed to send the outage alert; will retry on the next poll")
            return False
        log.warning("Outage alert sent to %s", self.notify)
        return True
