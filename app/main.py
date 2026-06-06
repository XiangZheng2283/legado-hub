"""FastAPI app factory and route registration."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import config
from app.api import health, legado, admin
from app.storage.db import initialize_database
from app.web import debug, admin as admin_web


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(legado.router)
    app.include_router(admin.router)
    app.include_router(debug.router)
    app.include_router(admin_web.router)
    return app


app = create_app()
