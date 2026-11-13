"""App factory. Run with: ``uvicorn --factory app.main:create_app``."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .poller import Poller
from .sources import build_source
from .store import SnapshotStore
from .web import router

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                   headers={"User-Agent": settings.user_agent})
        source = build_source(settings, client)
        store = SnapshotStore(settings.effective_database_url)
        poller = Poller(source, settings.poll_interval, settings.collection_filter, store=store)
        poller.restore()
        app.state.poller = poller
        app.state.store = store
        task = asyncio.create_task(poller.run(), name="poller")
        log.info("Started in %s mode (%s); collecting %s; database %s", settings.app_env,
                 source.description, poller.collect.describe(), store.engine.url.render_as_string())
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

    app = FastAPI(title="CyberPatriot Scoreboard", lifespan=lifespan,
                  docs_url="/api/docs" if settings.app_env == "dev" else None, redoc_url=None)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.include_router(router)
    return app
