"""FastAPI app factory and route registration."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app import config
from app.api import health, legado, console, auth, subscribe
from app.services.aggregate_processor import AggregateProcessor
from app.services.source_ping_scheduler import SourcePingScheduler
from app.storage.db import initialize_database

FRONTEND_DIST = config.FRONTEND_DIST_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    from app.services.official_auth.manager import official_auth_manager

    # Clean up jobs that were left running from a previous server process.  Their
    # workers/tasks are gone, so keeping them as "running" would make new requests
    # wait forever on an orphan job.
    try:
        from app.services.search_jobs import SearchJobService

        _job_service = SearchJobService()
        for _job in _job_service.list_jobs(limit=500):
            if _job["status"] in {"pending", "running"}:
                _job_service.cancel_job(_job["jobId"])
    except Exception:
        pass

    # Migrate legacy plugin-directory Cookie.json files to the host store once.
    try:
        from app.services.cookie_store import migrate_legacy_plugin_cookies

        migrate_legacy_plugin_cookies()
    except Exception:
        pass

    # On startup, probe any plugin that has a saved cookie in the host store.
    try:
        from app.services.cookie_store import CookieStore

        cookie_store = CookieStore()
        for plugin_id in cookie_store.list_plugin_ids():
            await official_auth_manager.probe_saved_cookie_file(plugin_id)
    except Exception:
        # Startup should stay resilient even if the probe fails.
        pass

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
    app.include_router(auth.router)
    app.include_router(subscribe.router)
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

