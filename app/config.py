"""Runtime configuration, read from environment variables (or a local .env)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

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

    scoreboard_url: str = DEFAULT_SCOREBOARD_URL
    poll_interval: float = 60.0
    user_agent: str = "cpscoreboard/0.2"

    scrape_mode: ScrapeMode = ScrapeMode.live
    data_dir: Path = Path("data")
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

    @property
    def watch_team_list(self) -> list[str]:
        return [t.strip() for t in self.watch_teams.split(",") if t.strip()]

    @property
    def collection_filter(self) -> CollectionFilter:
        return CollectionFilter.from_strings(self.collect_locations, self.collect_divisions,
                                             self.watch_team_list)

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
        return self
