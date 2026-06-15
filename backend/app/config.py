"""Project configuration and metadata."""

import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
CONFIG_DIR = BACKEND_ROOT / "config"
DATA_DIR = BACKEND_ROOT / "data"
GENERATED_DIR = BACKEND_ROOT / "generated"
DB_PATH = DATA_DIR / "app.db"
PLUGINS_DIR = PROJECT_ROOT / "plugins" / "sources"
SOURCE_SEEDS_DIR = PROJECT_ROOT / "plugins" / "seeds"
AGGREGATE_CONFIG_PATH = CONFIG_DIR / "aggregate_source.json"
SOURCE_POOL_CONFIG_PATH = CONFIG_DIR / "source_pool.json"
AI_PROVIDER_CONFIG_PATH = DATA_DIR / "ai_provider.json"
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

APP_NAME = "LegadoHub"
APP_VERSION = "0.0.1"
APP_PHASE = "plugin-runtime-stage-3"

HOST = "127.0.0.1"
PORT = 8765

# Default proxy configuration
DEFAULT_PROXY_URL = "http://192.168.31.233:7890"

# Default User-Agent, kept in sync with backend/config/source_pool.json
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 26_4_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "FxiOS/121.0 Mobile/15E148 Safari/605.1.15"
)


def get_default_user_agent() -> str:
    """Return the global default User-Agent from source_pool.json if available."""
    try:
        data = json.loads(SOURCE_POOL_CONFIG_PATH.read_text(encoding="utf-8"))
        ua = data.get("default_user_agent", "")
        if isinstance(ua, str) and ua.strip():
            return ua.strip()
    except Exception:
        pass
    return DEFAULT_USER_AGENT

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
            "db_path": str(DB_PATH),
            "plugins_dir": str(PLUGINS_DIR),
            "source_seeds_dir": str(SOURCE_SEEDS_DIR),
            "frontend_dist_dir": str(FRONTEND_DIST_DIR),
        },
    }


