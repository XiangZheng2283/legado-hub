"""SQLite path and initialization.

The host database is rebuilt from scratch in this refactor. Old runtime/debug
tables are removed; only long-lived factual data and the new search-oriented
tables remain.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import DATA_DIR, DB_PATH

SCHEMA_VERSION = "5"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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
    book_id TEXT,
    book_name TEXT,
    chapter_title TEXT,
    file_path TEXT,
    content_hash TEXT,
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

-- Search subsystem: result-oriented persistence. No process events.

CREATE TABLE IF NOT EXISTS search_jobs (
    job_id TEXT PRIMARY KEY,
    keyword TEXT NOT NULL,
    normalized_keyword TEXT NOT NULL,
    source_scope TEXT NOT NULL DEFAULT '__default__',
    page INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at REAL,
    completed_at REAL,
    result_count INTEGER DEFAULT 0,
    source_count INTEGER DEFAULT 0,
    attempted_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    timeout_count INTEGER DEFAULT 0,
    elapsed_ms INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_search_jobs_normalized
    ON search_jobs (normalized_keyword, page, source_scope, status);

CREATE TABLE IF NOT EXISTS search_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_name TEXT,
    book_url TEXT NOT NULL,
    name TEXT,
    author TEXT,
    cover_url TEXT,
    intro TEXT,
    category TEXT,
    word_count TEXT,
    status TEXT,
    last_chapter TEXT,
    score INTEGER DEFAULT 0,
    raw_payload_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(job_id, source_id, book_url)
);

CREATE INDEX IF NOT EXISTS idx_search_results_job
    ON search_results (job_id);
CREATE INDEX IF NOT EXISTS idx_search_results_book
    ON search_results (name, author);


-- Book-centric search cache (replaces search_query_cache).
-- Truth source is book entities, not query snapshots.  TTL = 7 days.

CREATE TABLE IF NOT EXISTS book_search_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_mode TEXT NOT NULL,
    normalized_name TEXT NOT NULL DEFAULT '',
    normalized_author TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL,
    source_name TEXT DEFAULT '',
    raw_book_url TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    first_seen_at TEXT DEFAULT (datetime('now')),
    last_seen_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_book_search_cache_title
    ON book_search_cache (match_mode, normalized_name, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_book_search_cache_author
    ON book_search_cache (match_mode, normalized_author, last_seen_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_book_search_cache_unique_source_book
    ON book_search_cache (source_id, raw_book_url, match_mode);

-- Live acceptance checks (debugging/diagnostics, not long-lived facts).

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

-- Aggregate processing tasks.

CREATE TABLE IF NOT EXISTS aggregate_book_tasks (
    aggregate_book_id TEXT PRIMARY KEY,
    name TEXT,
    author TEXT,
    aggregate_payload_json TEXT,
    primary_book_id TEXT,
    primary_source_id TEXT,
    book_status TEXT DEFAULT 'unknown',
    total_chapters INTEGER DEFAULT 0,
    processed_chapters INTEGER DEFAULT 0,
    failed_chapters INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    interval_minutes INTEGER DEFAULT 30,
    last_check_time TEXT,
    next_check_time TEXT,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    ai_enabled INTEGER DEFAULT 0,
    last_processed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS aggregate_chapter_tasks (
    chapter_id TEXT PRIMARY KEY,
    aggregate_book_id TEXT NOT NULL,
    source_chapter_id TEXT,
    chapter_index INTEGER,
    title TEXT,
    status TEXT DEFAULT 'pending',
    content_length INTEGER DEFAULT 0,
    processed_content TEXT,
    last_processed_at TEXT,
    error TEXT,
    ai_model TEXT,
    ai_prompt_tokens INTEGER DEFAULT 0,
    ai_completion_tokens INTEGER DEFAULT 0,
    ai_total_tokens INTEGER DEFAULT 0,
    ai_latency_ms INTEGER DEFAULT 0,
    deviation_score REAL DEFAULT 0.0,
    ai_self_score REAL DEFAULT 0.0,
    fallback_source_id TEXT,
    source_alignment_json TEXT,
    retry_count INTEGER DEFAULT 0,
    next_retry_time TEXT,
    last_error_code TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS aggregate_ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_book_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    status TEXT,
    error TEXT,
    deviation_score REAL DEFAULT 0.0,
    ai_self_score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def _is_legacy_database(path: Path) -> bool:
    """Detect whether the existing DB still carries old tables that need rebuild."""
    if not path.exists():
        return False
    try:
        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?, ?, ?, ?)",
                ("plugin_health", "plugin_attempts", "search_job_events",
                 "plugin_runtime_state", "plugin_auth_state", "search_query_cache"),
            ).fetchall()
            if len(rows) > 0:
                return True
            # Also trigger rebuild if the DB schema version is older than 5
            # (pre-book_search_cache).
            try:
                ver = conn.execute(
                    "SELECT value FROM schema_meta WHERE key = 'version'"
                ).fetchone()
                if ver and ver[0] < SCHEMA_VERSION:
                    return True
            except Exception:
                pass
            return False
    except Exception:
        return False


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def initialize_database(db_path: Path | None = None) -> str:
    path = db_path or DB_PATH
    ensure_data_dir()

    # Phase-2 rebuild: if the existing database is from the old schema, delete it
    # and start fresh. This matches the "direct rebuild, no compatibility" rule.
    if _is_legacy_database(path):
        try:
            path.unlink()
        except OSError:
            pass

    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("version", SCHEMA_VERSION),
        )
        conn.commit()
    return str(path)
