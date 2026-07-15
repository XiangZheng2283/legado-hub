"""Project configuration and metadata."""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
CONFIG_DIR = BACKEND_ROOT / "config"
DATA_DIR = BACKEND_ROOT / "data"
GENERATED_DIR = BACKEND_ROOT / "generated"
RUNTIME_DIR = BACKEND_ROOT / "runtime"
DB_PATH = DATA_DIR / "app.db"
PLUGINS_DIR = PROJECT_ROOT / "plugins" / "sources"
SOURCE_SEEDS_DIR = PROJECT_ROOT / "plugins" / "seeds"
APP_CONFIG_PATH = CONFIG_DIR / "app_config.json"
COOKIE_DIR = CONFIG_DIR / "cookies"
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

APP_NAME = "LegadoHub"
APP_VERSION = "0.0.1"
APP_PHASE = "plugin-runtime-stage-3"

HOST = "127.0.0.1"
PORT = 8765


def get_default_user_agent() -> str:
    """Return the global default User-Agent from app_config.json if available."""
    try:
        from app.core.app_config import AppConfig

        ua = AppConfig.get().search.default_user_agent
        if isinstance(ua, str) and ua.strip():
            return ua.strip()
    except Exception:
        pass
    return ""


def get_app_info() -> dict:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "phase": APP_PHASE,
        "paths": {
            "backend_root": str(BACKEND_ROOT),
            "project_root": str(PROJECT_ROOT),
            "config_dir": str(CONFIG_DIR),
            "data_dir": str(DATA_DIR),
            "generated_dir": str(GENERATED_DIR),
            "runtime_dir": str(RUNTIME_DIR),
            "db_path": str(DB_PATH),
            "plugins_dir": str(PLUGINS_DIR),
            "source_seeds_dir": str(SOURCE_SEEDS_DIR),
            "frontend_dist_dir": str(FRONTEND_DIST_DIR),
        },
    }
