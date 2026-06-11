"""FastAPI app factory and route registration."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app import config
from app.api import health, legado, console
from app.services.aggregate_processor import AggregateProcessor
from app.services.source_ping_scheduler import SourcePingScheduler
from app.storage.db import initialize_database

FRONTEND_DIST = config.FRONTEND_DIST_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    stop_event = asyncio.Event()
    aggregate_task = asyncio.create_task(AggregateProcessor().run_forever(stop_event))
    ping_task = asyncio.create_task(SourcePingScheduler().run_forever(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        aggregate_task.cancel()
        ping_task.cancel()
        try:
            await aggregate_task
        except asyncio.CancelledError:
            pass
        try:
            await ping_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(legado.router)
    app.include_router(console.console_router)
    # Serve React console frontend.
    if FRONTEND_DIST.exists():
        app.mount("/console-static", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="console-static")
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="console-assets")

        @app.get("/console")
        async def console_spa():
            return FileResponse(str(FRONTEND_DIST / "index.html"))

        @app.get("/console/{path:path}")
        async def console_spa_catchall(path: str):
            return FileResponse(str(FRONTEND_DIST / "index.html"))

        @app.get("/favicon.svg")
        async def console_favicon():
            return FileResponse(str(FRONTEND_DIST / "favicon.svg"))

        @app.get("/icons.svg")
        async def console_icons():
            return FileResponse(str(FRONTEND_DIST / "icons.svg"))

    return app


app = create_app()


