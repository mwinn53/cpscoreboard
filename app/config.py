"""Runtime configuration, read from environment variables (or a local .env)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .collection import CollectionFilter

DEFAULT_SCOREBOARD_URL = "https://scoreboard.uscyberpatriot.org/api/team/scores.php"


class AppEnv(StrEnum):
    dev = "dev"
    prod = "prod"


class ScrapeMode(StrEnum):
    live = "live"        # poll the real scoreboard
    capture = "capture"  # poll the real scoreboard and save each changed response (dev only)
    replay = "replay"    # play back a saved capture set instead of polling (dev only)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: AppEnv = AppEnv.dev
    log_level: str = "INFO"
    # Shown in the header, browser tabs, and email subjects/sender name.
    site_title: str = "EMS CyberPatriot Next Generation Scorebot"
    # Time zone for times shown on the site (the database stays in UTC).
    display_timezone: str = "America/New_York"

    scoreboard_url: str = DEFAULT_SCOREBOARD_URL
    poll_interval: float = 60.0
    user_agent: str = "cpscoreboard/0.2"

    scrape_mode: ScrapeMode = ScrapeMode.live
    data_dir: Path = Path("data")
    # Default: SQLite at <data_dir>/cpscoreboard.db; in replay mode an in-memory database,
    # so replays never mix into real history. Set explicitly to override either.
    database_url: str | None = None
    capture_dir: Path = Path("captures")
    # Replay: a folder name under capture_dir, or a path to any folder of captures.
    capture_set: str | None = None
    replay_speed: float = 1.0
    replay_loop: bool = False

    # Collection criteria: comma-separated, case-insensitive; empty = keep all.
    # Places are still computed on the full board before filtering.
    collect_locations: str = ""   # e.g. "VA,MD,DC"
    collect_divisions: str = ""   # e.g. "Open,Middle School"

    # Comma-separated team numbers to pin on the dashboard (always collected).
    # Temporary until milestone 3 moves the watchlist into the database.
    watch_teams: str = ""
    # Dashboard view, first start only (then edited on /admin/board): which division and
    # state the scoreboard opens on (blank = follow the collection filter, else all), and
    # the heading for the watched teams.
    default_division: str = ""
    default_state: str = ""
    watch_label: str = "Watchlist"
    watch_school: str = ""  # School column for watched teams not listed as district schools
    # Keep the full raw scoreboard, one file per day, in <DATA_DIR>/archive (live and capture
    # modes; never in replay). See app/archive.py.
    archive_enabled: bool = True
    # Outage alert (app/outage.py): email ADMIN_NOTIFY_EMAIL when the public scoreboard has
    # been down this long, counting from this long after the competition starts.
    outage_alert_hours: float = 24
    outage_grace_hours: float = 72
    # The site's own address, for links in emails (e.g. https://cpscores.example.org).
    public_url: str = ""
    # Self-shutdown from /admin/server (set by Terraform in prod; blank = not available).
    aws_instance_id: str = ""
    data_volume_id: str = ""

    # --- Access control (milestone 4) ---
    # Viewers register a browser with an emailed code; the admin approves it.
    # Prod always requires it; dev can turn it off for convenience.
    auth_enabled: bool = True
    # Secret that lets a registered device claim admin at /admin/claim. Unset = no claiming.
    admin_bootstrap_token: str | None = None
    # Where "new device waiting for approval" emails go. Unset = admin page only.
    admin_notify_email: str | None = None
    device_lifetime_days: int = 365

    # --- Email ---
    mail_backend: str = "auto"  # auto | ses | smtp | console (auto: smtp if SMTP_HOST, ses in prod, else console)
    mail_from: str = "noreply@localhost"
    mail_from_name: str = ""  # blank = SITE_TITLE
    smtp_host: str | None = None
    smtp_port: int = 1025
    aws_region: str = "us-east-1"

    @property
    def secure_cookies(self) -> bool:
        return self.app_env is AppEnv.prod

    @property
    def watch_team_list(self) -> list[str]:
        return [t.strip() for t in self.watch_teams.split(",") if t.strip()]

    @property
    def collection_filter(self) -> CollectionFilter:
        return CollectionFilter.from_strings(self.collect_locations, self.collect_divisions,
                                             self.watch_team_list)

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.scrape_mode is ScrapeMode.replay:
            return "sqlite://"
        return f"sqlite:///{(self.data_dir / 'cpscoreboard.db').as_posix()}"

    @property
    def capture_set_path(self) -> Path | None:
        if not self.capture_set:
            return None
        direct = Path(self.capture_set)
        return direct if direct.is_dir() else self.capture_dir / self.capture_set

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.app_env is AppEnv.prod and self.scrape_mode is not ScrapeMode.live:
            raise ValueError("SCRAPE_MODE must be 'live' when APP_ENV=prod (prod never captures or replays)")
        if self.scrape_mode is ScrapeMode.replay and not self.capture_set:
            raise ValueError("SCRAPE_MODE=replay requires CAPTURE_SET")
        if self.poll_interval <= 0 or self.replay_speed <= 0:
            raise ValueError("POLL_INTERVAL and REPLAY_SPEED must be positive")
        if self.app_env is AppEnv.prod and not self.auth_enabled:
            raise ValueError("AUTH_ENABLED can't be false when APP_ENV=prod")
        if self.mail_backend not in ("auto", "ses", "smtp", "console"):
            raise ValueError("MAIL_BACKEND must be auto, ses, smtp or console")
        if self.admin_bootstrap_token is not None and len(self.admin_bootstrap_token) < 16:
            raise ValueError("ADMIN_BOOTSTRAP_TOKEN must be at least 16 characters")
        try:
            ZoneInfo(self.display_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"DISPLAY_TIMEZONE {self.display_timezone!r} isn't a time zone name like America/New_York") from None
        return self
