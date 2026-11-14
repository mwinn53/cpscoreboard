"""App factory. Run with: ``uvicorn --factory app.main:create_app``."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import admin_board, auth, web
from .board_config import BoardConfig
from .config import Settings
from .devices import DeviceStore
from .mail import Mailer, build_mailer
from .poller import Poller
from .sources import build_source
from .store import SnapshotStore

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, mailer: Mailer | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                   headers={"User-Agent": settings.user_agent})
        source = build_source(settings, client)
        store = SnapshotStore(settings.effective_database_url)
        app.state.devices = DeviceStore(store, timedelta(days=settings.device_lifetime_days))
        board = BoardConfig(store)
        board.seed(settings.watch_team_list, settings.collect_locations, settings.collect_divisions)
        app.state.board = board
        poller = Poller(source, settings.poll_interval, board.collection_filter(), store=store)
        poller.restore()
        app.state.poller = poller
        app.state.store = store
        task = asyncio.create_task(poller.run(), name="poller")
        log.info("Started in %s mode (%s); collecting %s; database %s; email via %s; access control %s",
                 settings.app_env, source.description, poller.collect.describe(),
                 store.engine.url.render_as_string(), app.state.mailer.description,
                 "ON" if settings.auth_enabled else "OFF")
        if settings.auth_enabled and not settings.admin_bootstrap_token:
            log.warning("ADMIN_BOOTSTRAP_TOKEN is not set, so nobody can claim admin at /admin/claim")
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await poller.drain()
            await source.aclose()
            await client.aclose()
            store.close()

    dev = settings.app_env == "dev"
    app = FastAPI(title="CyberPatriot Scoreboard", lifespan=lifespan, redoc_url=None,
                  docs_url="/api/docs" if dev else None, openapi_url="/openapi.json" if dev else None)
    app.state.settings = settings
    app.state.mailer = mailer or build_mailer(settings)
    app.add_exception_handler(auth.NotAllowed, auth.not_allowed_handler)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.include_router(web.public_router)
    app.include_router(auth.router)
    app.include_router(admin_board.router)
    app.include_router(web.router)
    return app
