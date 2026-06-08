"""SQLite path and initialization."""

import sqlite3
from pathlib import Path

from app.config import DATA_DIR, DB_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT,
    source_type TEXT,
    enabled INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 0,
    config TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    author TEXT,
    cover_url TEXT,
    intro TEXT,
    category TEXT,
    word_count TEXT,
    status TEXT,
    last_chapter TEXT,
    last_update_time TEXT,
    sources TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    content TEXT,
    cached INTEGER DEFAULT 0,
    source TEXT,
    update_time TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(book_id, chapter_id)
);

CREATE TABLE IF NOT EXISTS update_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT UNIQUE NOT NULL,
    last_check_time TEXT,
    next_check_time TEXT,
    status TEXT DEFAULT 'active',
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS search_cache (
    keyword TEXT NOT NULL,
    page INTEGER NOT NULL,
    response_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (keyword, page)
);

CREATE TABLE IF NOT EXISTS book_cache (
    book_id TEXT PRIMARY KEY,
    source_id TEXT,
    book_url TEXT,
    response_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS toc_cache (
    book_id TEXT PRIMARY KEY,
    response_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chapter_cache (
    chapter_id TEXT PRIMARY KEY,
    source_id TEXT,
    chapter_url TEXT,
    response_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plugin_runtime_state (
    plugin_id TEXT PRIMARY KEY,
    proxy_mode TEXT,
    proxy_status TEXT,
    last_direct_error TEXT,
    last_proxy_error TEXT,
    last_success_via_proxy INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Phase 3 extensions

CREATE TABLE IF NOT EXISTS plugin_health (
    plugin_id TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    health_status TEXT DEFAULT 'unknown',
    last_check_at TEXT,
    last_success_at TEXT,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    avg_latency_ms INTEGER,
    last_error TEXT,
    parser_capabilities_json TEXT,
    plugin_name TEXT,
    failure_reason TEXT,
    proxy_mode TEXT DEFAULT 'auto',
    proxy_status TEXT,
    last_test_result_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plugin_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id TEXT,
    stage TEXT,
    url TEXT,
    direct_status TEXT,
    proxy_status TEXT,
    proxy_used INTEGER DEFAULT 0,
    latency_ms INTEGER,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS book_records (
    book_id TEXT PRIMARY KEY,
    name TEXT,
    author TEXT,
    merged_sources_json TEXT,
    selected_source_id TEXT,
    last_chapter TEXT,
    last_seen_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS aggregate_progress (
    key TEXT PRIMARY KEY,
    value_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admin_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plugin_auth_state (
    plugin_id TEXT PRIMARY KEY,
    auth_status TEXT DEFAULT 'unknown',
    account_name TEXT,
    cookie_json TEXT,
    expires_at TEXT,
    last_checked_at TEXT,
    last_error TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plugin_live_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id TEXT NOT NULL,
    keyword TEXT NOT NULL,
    status TEXT NOT NULL,
    search_count INTEGER DEFAULT 0,
    selected_name TEXT,
    selected_author TEXT,
    toc_count INTEGER DEFAULT 0,
    chapter_title TEXT,
    content_length INTEGER DEFAULT 0,
    result_json TEXT,
    error_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

CURRENT_PLUGIN_HEALTH_COLUMNS = {
    "plugin_id": "TEXT PRIMARY KEY",
    "enabled": "INTEGER DEFAULT 1",
    "health_status": "TEXT DEFAULT 'unknown'",
    "last_check_at": "TEXT",
    "last_success_at": "TEXT",
    "success_count": "INTEGER DEFAULT 0",
    "failure_count": "INTEGER DEFAULT 0",
    "avg_latency_ms": "INTEGER",
    "last_error": "TEXT",
    "parser_capabilities_json": "TEXT",
    "plugin_name": "TEXT",
    "failure_reason": "TEXT",
    "proxy_mode": "TEXT DEFAULT 'auto'",
    "proxy_status": "TEXT",
    "last_test_result_json": "TEXT",
    "updated_at": "TEXT DEFAULT (datetime('now'))",
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def ensure_current_schema(conn: sqlite3.Connection) -> None:
    """Ensure existing databases match the current schema contract."""
    rows = conn.execute("PRAGMA table_info(plugin_health)").fetchall()
    existing_columns = {row[1] for row in rows}
    for column_name, column_sql in CURRENT_PLUGIN_HEALTH_COLUMNS.items():
        if column_name in existing_columns:
            continue
        conn.execute(f"ALTER TABLE plugin_health ADD COLUMN {column_name} {column_sql}")


def initialize_database(db_path: Path | None = None) -> str:
    path = db_path or DB_PATH
    ensure_data_dir()
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        ensure_current_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("version", "3"),
        )
        conn.commit()
    return str(path)
