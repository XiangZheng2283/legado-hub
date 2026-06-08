"""Project configuration and metadata."""

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
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

APP_NAME = "LegadoHub"
APP_VERSION = "0.0.1"
APP_PHASE = "plugin-runtime-stage-3"

HOST = "127.0.0.1"
PORT = 8765

# Default proxy configuration
DEFAULT_PROXY_URL = "http://192.168.31.233:7890"

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
