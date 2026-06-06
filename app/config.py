"""Project configuration and metadata."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
GENERATED_DIR = PROJECT_ROOT / "generated"
DB_PATH = DATA_DIR / "app.db"

APP_NAME = "LegadoHub"
APP_VERSION = "0.0.1"
APP_PHASE = "kernel-phase-1"

HOST = "127.0.0.1"
PORT = 8765

# Default proxy configuration
DEFAULT_PROXY_URL = "http://192.168.31.233:7890"

# Source repository paths
RAW_SOURCES_DIR = DATA_DIR / "sources" / "raw" / "by-site" / "legado"


def get_app_info() -> dict:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "phase": APP_PHASE,
        "paths": {
            "project_root": str(PROJECT_ROOT),
            "data_dir": str(DATA_DIR),
            "generated_dir": str(GENERATED_DIR),
            "db_path": str(DB_PATH),
            "raw_sources_dir": str(RAW_SOURCES_DIR),
        },
    }
