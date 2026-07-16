from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.aggregate_processor import AggregateProcessor
from app.services.book_catalog import BookCatalog
from app.services.library_books import LibraryBooksService, make_library_book_id
from app.services.official_auth.manager import official_auth_manager
from app.services.shared_book_storage import SharedBookStorage
from app.services.user_auth import UserAuthService
from app.services.user_subscriptions import UserSubscriptionsService
from app.storage.db import initialize_database


DEFAULT_GROUP = {
    "candidateId": "real-run-default",
    "name": "宿命之环",
    "author": "爱潜水的乌贼",
    "items": [
        {
            "sourceId": "qidian_com_web",
            "sourceName": "起点中文网(Web)",
            "rawBookUrl": "https://m.qidian.com/book/1036370336/",
            "bookUrl": "https://m.qidian.com/book/1036370336/",
            "coverUrl": "https://bookcover.yuewen.com/qdbimg/349573/1036370336/180",
            "intro": "诡秘世界第二部。1368之年，七月之末，深红将从天而降。",
            "wordCount": "377.04万字",
            "status": "完本",
            "chapterCount": 1195,
            "score": 221,
            "lastChapter": "番外：科尔杜村日常",
            "name": "宿命之环",
            "author": "爱潜水的乌贼",
        }
    ],
}


class NoOpAggregateAIService:
    async def process_official_full(self, *, book_name: str, author: str, title: str, content: str) -> dict:
        return {
            "status": "processed",
            "content": content,
            "selfScore": 0.0,
            "aiModel": "",
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
            "latencyMs": 0,
            "plannedAnalysis": False,
        }

    async def process_third_party_primary(
        self,
        *,
        book_name: str,
        author: str,
        title: str,
        content: str,
        source_id: str,
        previous_context: str = "",
    ) -> dict:
        return {
            "status": "processed",
            "content": content,
            "selfScore": 0.0,
            "aiModel": "",
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
            "latencyMs": 0,
            "plannedAnalysis": False,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real shared-subscription ingestion check.")
    parser.add_argument("--keyword", default=DEFAULT_GROUP["name"], help="Display name for the subscription book")
    parser.add_argument("--author", default=DEFAULT_GROUP["author"], help="Display author for the subscription book")
    parser.add_argument("--book-url", default=DEFAULT_GROUP["items"][0]["rawBookUrl"], help="Official source book URL")
    parser.add_argument("--source-id", default=DEFAULT_GROUP["items"][0]["sourceId"], help="Official source id")
    parser.add_argument("--source-name", default=DEFAULT_GROUP["items"][0]["sourceName"], help="Official source name")
    parser.add_argument("--start-chapter-index", type=int, default=12)
    parser.add_argument("--auto-archive", action="store_true", default=False)
    parser.add_argument("--rounds", type=int, default=6, help="Bootstrap rounds to run")
    parser.add_argument("--chapter-limit", type=int, default=50, help="Per-round chapter processing limit")
    parser.add_argument("--use-main-db", action="store_true", help="Operate directly on backend/data/app.db")
    parser.add_argument("--confirm-main-db", action="store_true", help="Required with --use-main-db to allow persistent writes")
    parser.add_argument("--keep-temp-db", action="store_true", help="Keep copied temp db directory for inspection")
    parser.add_argument("--reset-existing", action="store_true", help="Delete existing aggregate book for the same primary url before running")
    parser.add_argument("--cleanup-existing-only", action="store_true", help="Delete existing aggregate book for the same primary url and exit")
    parser.add_argument("--reuse-existing", action="store_true", help="Reuse existing aggregate book instead of failing when found")
    parser.add_argument("--rollback-created", action="store_true", help="Delete the newly created aggregate book after outputting verification data")
    parser.add_argument("--rollback-created-admin", action="store_true", help="Delete the admin user created by --ensure-admin when this run created it")
    parser.add_argument("--ensure-admin", action="store_true", help="Ensure default admin exists in the target db before running")
    parser.add_argument("--added-by-username", default="admin", help="Username recorded as the subscriber when available")
    parser.add_argument("--preflight", action="store_true", help="Read-only readiness check: auth probe, users, existing book, detail/toc")
    parser.add_argument("--real-ai", action="store_true", help="Use the configured real AI provider instead of disabling AI during this run")
    return parser.parse_args()


def build_group(args: argparse.Namespace) -> dict:
    item = dict(DEFAULT_GROUP["items"][0])
    item["sourceId"] = args.source_id
    item["sourceName"] = args.source_name
    item["rawBookUrl"] = args.book_url
    item["bookUrl"] = args.book_url
    item["name"] = args.keyword
    item["author"] = args.author
    return {
        "candidateId": f"real-run:{args.source_id}:{args.book_url}",
        "name": args.keyword,
        "author": args.author,
        "items": [item],
    }


def prepare_db(use_main_db: bool) -> tuple[Path, Path | None]:
    main_db = BACKEND_ROOT / "data" / "app.db"
    if use_main_db:
        initialize_database(main_db)
        return main_db, None
    workdir = Path(tempfile.mkdtemp(prefix="legadohub_real_run_"))
    db_path = workdir / "app.db"
    if main_db.exists():
        shutil.copy2(main_db, db_path)
    else:
        initialize_database(db_path)
    initialize_database(db_path)
    return db_path, workdir


def summarize_book(conn: sqlite3.Connection, aggregate_book_id: str) -> dict:
    row = conn.execute(
        """
        SELECT aggregate_book_id, name, author, status, book_status, total_chapters,
               processed_chapters, visible_processed_chapters, failed_chapters,
               search_visibility_status, primary_source_id, primary_book_url, primary_toc_url
        FROM aggregate_book_tasks
        WHERE aggregate_book_id = ?
        """,
        (aggregate_book_id,),
    ).fetchone()
    if not row:
        return {}
    chapter_stats = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END),
            SUM(CASE WHEN status = 'fallback' THEN 1 ELSE 0 END),
            SUM(CASE WHEN preview_only = 1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END)
        FROM aggregate_chapter_tasks
        WHERE aggregate_book_id = ?
        """,
        (aggregate_book_id,),
    ).fetchone()
    return {
        "aggregateBookId": row[0],
        "name": row[1],
        "author": row[2],
        "status": row[3],
        "bookStatus": row[4],
        "totalChapters": int(row[5] or 0),
        "processedChapters": int(row[6] or 0),
        "visibleProcessedChapters": int(row[7] or 0),
        "failedChapters": int(row[8] or 0),
        "searchVisibilityStatus": row[9],
        "primarySourceId": row[10],
        "primaryBookUrl": row[11],
        "primaryTocUrl": row[12],
        "chapterStats": {
            "processed": int(chapter_stats[0] or 0),
            "fallback": int(chapter_stats[1] or 0),
            "previewOnly": int(chapter_stats[2] or 0),
            "pending": int(chapter_stats[3] or 0),
        },
    }


def db_counters(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "users": int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0),
        "aggregateBookTasks": int(conn.execute("SELECT COUNT(*) FROM aggregate_book_tasks").fetchone()[0] or 0),
        "aggregateChapterTasks": int(conn.execute("SELECT COUNT(*) FROM aggregate_chapter_tasks").fetchone()[0] or 0),
    }


def inspect_chapter_file(file_path: str) -> dict:
    path = Path(file_path or "")
    if not path or not path.exists():
        return {"exists": False, "hasTraceBlock": False, "tail": ""}
    text = path.read_text(encoding="utf-8")
    start = text.find("LEGADOHUB_TRACE_BEGIN")
    end = text.find("LEGADOHUB_TRACE_END")
    trace_block = ""
    if start >= 0 and end >= start:
        trace_block = text[start : end + len("LEGADOHUB_TRACE_END")]
    tail = trace_block or text[-800:]
    return {
        "exists": True,
        "hasTraceBlock": "LEGADOHUB_TRACE_BEGIN" in text and "LEGADOHUB_TRACE_END" in text,
        "hasPrimarySourceChapterUrl": '"primarySourceChapterUrl":' in tail,
        "hasSourceWordCount": '"sourceWordCount":' in tail,
        "hasPreviewMarker": '"previewOnly":' in tail,
        "tail": tail,
    }


def inspect_reading_contract(service: LibraryBooksService, aggregate_book_id: str) -> dict:
    """Read the published shared book through the same service used by Legado routes."""
    book_id = make_library_book_id(aggregate_book_id)
    base_api = "http://127.0.0.1:8765"
    detail = service.legado_book_detail(book_id, base_api=base_api)
    toc = service.legado_toc(book_id, base_api=base_api)
    chapters = (toc or {}).get("chapters") or []
    free_sample = next((item for item in chapters if not item.get("previewOnly")), None)
    preview_sample = next((item for item in chapters if item.get("previewOnly")), None)
    free_body = service.legado_chapter(free_sample["chapterId"]) if free_sample else None
    preview_body = service.legado_chapter(preview_sample["chapterId"]) if preview_sample else None
    return {
        "published": bool(detail),
        "bookId": book_id,
        "chapterCount": len(chapters),
        "freeChapter": {
            "found": bool(free_body),
            "contentLength": len(str((free_body or {}).get("content", "") or "")),
            "contentAccess": ((free_body or {}).get("extra") or {}).get("contentAccess", ""),
            "hasReplacementCharacter": "\ufffd" in str((free_body or {}).get("content", "") or ""),
        },
        "previewChapter": {
            "found": bool(preview_body),
            "contentLength": len(str((preview_body or {}).get("content", "") or "")),
            "contentAccess": ((preview_body or {}).get("extra") or {}).get("contentAccess", ""),
            "isVip": bool((preview_body or {}).get("isVip")),
        },
    }


def find_existing_book(conn: sqlite3.Connection, source_id: str, book_url: str) -> dict | None:
    row = conn.execute(
        """
        SELECT aggregate_book_id, name, status
        FROM aggregate_book_tasks
        WHERE primary_source_id = ? AND primary_book_url = ?
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        """,
        (source_id, book_url),
    ).fetchone()
    if not row:
        return None
    return {"aggregateBookId": row[0], "name": row[1], "status": row[2]}


def delete_aggregate_book(conn: sqlite3.Connection, aggregate_book_id: str) -> None:
    content_rows = conn.execute(
        """
        SELECT content_file_path
        FROM aggregate_chapter_tasks
        WHERE aggregate_book_id = ? AND content_file_path IS NOT NULL AND content_file_path != ''
        """,
        (aggregate_book_id,),
    ).fetchall()
    for (path_str,) in content_rows:
        path = Path(path_str)
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    conn.execute("DELETE FROM aggregate_source_snapshots WHERE aggregate_book_id = ?", (aggregate_book_id,))
    conn.execute("DELETE FROM aggregate_operation_logs WHERE aggregate_book_id = ?", (aggregate_book_id,))
    conn.execute("DELETE FROM aggregate_book_sources WHERE aggregate_book_id = ?", (aggregate_book_id,))
    conn.execute("DELETE FROM aggregate_chapter_tasks WHERE aggregate_book_id = ?", (aggregate_book_id,))
    conn.execute("DELETE FROM aggregate_book_tasks WHERE aggregate_book_id = ?", (aggregate_book_id,))
    conn.execute("DELETE FROM book_records WHERE book_id = ?", (aggregate_book_id,))
    conn.commit()


def resolve_actor_user_id(db_path: Path, username: str) -> tuple[str, dict[str, str]]:
    auth = UserAuthService(db_path)
    user = auth.get_user_by_username(username)
    if user:
        return user["userId"], {"username": username, "userId": user["userId"]}
    users = auth.list_users()
    if users:
        first = users[0]
        return first["userId"], {"username": first["username"], "userId": first["userId"]}
    raise RuntimeError("target database has no users; rerun with --ensure-admin")


def delete_user(conn: sqlite3.Connection, user_id: str) -> None:
    if not user_id:
        return
    conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()


async def run_preflight(db_path: Path, args: argparse.Namespace, actor_info: dict[str, str]) -> dict:
    auth = UserAuthService(db_path)
    users = auth.list_users()
    with sqlite3.connect(db_path) as conn:
        existing = find_existing_book(conn, args.source_id, args.book_url)
    auth_probe = await official_auth_manager.probe_saved_cookie_file(args.source_id)
    catalog = BookCatalog()
    source_book_id = LibraryBooksService(db_path=db_path)._payload_from_group(build_group(args))["sources"][0]["bookId"]
    detail = await catalog.book_detail(source_book_id)
    detail_data = detail.get("data") if isinstance(detail, dict) else {}
    toc = await catalog.toc(source_book_id)
    chapters = toc.get("chapters") if isinstance(toc, dict) else []
    return {
        "dbPath": str(db_path),
        "mode": "preflight",
        "users": {
            "count": len(users),
            "items": [
                {
                    "userId": item.get("userId", ""),
                    "username": item.get("username", ""),
                    "role": item.get("role", ""),
                    "disabled": bool(item.get("disabled", False)),
                }
                for item in users
            ],
        },
        "actor": actor_info,
        "existingBook": existing or {},
        "authProbe": auth_probe,
        "detail": {
            "name": detail_data.get("name", "") if isinstance(detail_data, dict) else "",
            "author": detail_data.get("author", "") if isinstance(detail_data, dict) else "",
            "kind": detail_data.get("kind", "") if isinstance(detail_data, dict) else "",
            "bookUrl": detail_data.get("rawBookUrl", "") if isinstance(detail_data, dict) else "",
            "tocUrl": detail_data.get("rawTocUrl", "") if isinstance(detail_data, dict) else "",
        },
        "toc": {
            "count": len(chapters) if isinstance(chapters, list) else 0,
            "firstTitle": chapters[0].get("title", "") if isinstance(chapters, list) and chapters else "",
            "lastTitle": chapters[-1].get("title", "") if isinstance(chapters, list) and chapters else "",
        },
        "realAiEnabled": bool(args.real_ai),
    }


async def main() -> int:
    args = parse_args()
    if args.use_main_db and not args.confirm_main_db:
        print("--use-main-db requires --confirm-main-db")
        return 1
    group = build_group(args)
    db_path, temp_dir = prepare_db(args.use_main_db)
    initialize_database(db_path)

    admin_info: dict[str, str] = {}
    created_admin_user_id = ""
    if args.ensure_admin:
        auth = UserAuthService(db_path)
        password = auth.ensure_default_admin()
        if password:
            created_admin = auth.get_user_by_username("admin") or {}
            created_admin_user_id = created_admin.get("userId", "") or ""
            admin_info = {
                "username": "admin",
                "password": password,
                "created": "true",
                "userId": created_admin_user_id,
            }
        else:
            existing_admin = auth.get_user_by_username("admin") or {}
            admin_info = {
                "username": "admin",
                "password": "(existing user set not changed)",
                "created": "false",
                "userId": existing_admin.get("userId", "") or "",
            }
    added_by_user_id, actor_info = resolve_actor_user_id(db_path, args.added_by_username)
    if args.preflight:
        output = await run_preflight(db_path, args, actor_info)
        output["admin"] = admin_info
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if temp_dir and not args.keep_temp_db:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return 0

    storage = SharedBookStorage(root=db_path.parent / "library")
    service = LibraryBooksService(db_path=db_path, shared_book_storage=storage)
    subscriptions = UserSubscriptionsService(db_path=db_path)
    ai_service = None if args.real_ai else NoOpAggregateAIService()
    existing: dict | None = None
    deleted_existing: dict | None = None
    baseline_counts: dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        baseline_counts = db_counters(conn)
        existing = find_existing_book(conn, args.source_id, args.book_url)
        if existing and args.reset_existing:
            deleted_existing = dict(existing)
            delete_aggregate_book(conn, existing["aggregateBookId"])
            existing = None
        elif existing and args.cleanup_existing_only:
            deleted_existing = dict(existing)
            delete_aggregate_book(conn, existing["aggregateBookId"])
            existing = None

    if args.cleanup_existing_only:
        output = {
            "dbPath": str(db_path),
            "tempDir": str(temp_dir) if temp_dir else "",
            "admin": admin_info,
            "actor": actor_info,
            "deletedExisting": deleted_existing or {},
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if temp_dir and not args.keep_temp_db:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return 0

    if existing and args.reuse_existing:
        subscription, _ = subscriptions.ensure(
            added_by_user_id,
            existing["aggregateBookId"],
            start_chapter_index=args.start_chapter_index,
            auto_archive_on_complete=args.auto_archive,
        )
        processor = AggregateProcessor(db_path=db_path, ai_service=ai_service)
        payload = service.load_payload(existing["aggregateBookId"])
        enqueue = processor.enqueue_book(existing["aggregateBookId"], payload)
        results = []
        for _ in range(max(1, args.rounds)):
            result = await processor.run_book_task(existing["aggregateBookId"], chapter_limit=max(1, args.chapter_limit))
            results.append(result)
            pending = processor._pending_chapter_count(existing["aggregateBookId"])
            if pending <= 0:
                break
        with sqlite3.connect(db_path) as conn:
            summary = summarize_book(conn, existing["aggregateBookId"])
            chapter_sample = conn.execute(
                """
                SELECT chapter_index, title, status, preview_only, source_word_count, primary_source_chapter_url, content_file_path
                FROM aggregate_chapter_tasks
                WHERE aggregate_book_id = ?
                ORDER BY chapter_index ASC
                LIMIT 8
                """,
                (existing["aggregateBookId"],),
            ).fetchall()
        output = {
            "dbPath": str(db_path),
            "tempDir": str(temp_dir) if temp_dir else "",
            "admin": admin_info,
            "actor": actor_info,
            "deletedExisting": deleted_existing or {},
            "reusedExisting": existing,
            "subscription": subscription,
            "enqueue": enqueue,
            "rounds": results,
            "summary": summary,
            "chapterSample": [
                {
                    "chapterIndex": row[0],
                    "title": row[1],
                    "status": row[2],
                    "previewOnly": bool(row[3]),
                    "sourceWordCount": int(row[4] or 0),
                    "primarySourceChapterUrl": row[5] or "",
                    "contentFilePath": row[6] or "",
                }
                for row in chapter_sample
            ],
            "readingContract": inspect_reading_contract(service, existing["aggregateBookId"]),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if temp_dir and not args.keep_temp_db:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return 0

    created = await service.create_or_get_shared_book(
        group,
        actor_user_id=added_by_user_id,
    )
    if not created.get("created"):
        print("subscription already existed in target db")
        print(json.dumps(created.get("book", {}), ensure_ascii=False, indent=2))
        return 1

    book = created["book"]
    payload = created["payload"]
    subscription, subscription_created = subscriptions.ensure(
        added_by_user_id,
        book["aggregateBookId"],
        start_chapter_index=args.start_chapter_index,
        auto_archive_on_complete=args.auto_archive,
    )
    processor = AggregateProcessor(db_path=db_path, ai_service=ai_service)
    enqueue = processor.enqueue_book(book["aggregateBookId"], payload)

    results = []
    for _ in range(max(1, args.rounds)):
        result = await processor.run_book_task(book["aggregateBookId"], chapter_limit=max(1, args.chapter_limit))
        results.append(result)
        pending = processor._pending_chapter_count(book["aggregateBookId"])
        if pending <= 0:
            break

    with sqlite3.connect(db_path) as conn:
        summary = summarize_book(conn, book["aggregateBookId"])
        chapter_sample = conn.execute(
            """
            SELECT chapter_index, title, status, preview_only, source_word_count, primary_source_chapter_url, content_file_path
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ?
            ORDER BY chapter_index ASC
            LIMIT 8
            """,
            (book["aggregateBookId"],),
        ).fetchall()
        processed_sample = conn.execute(
            """
            SELECT chapter_index, title, status, preview_only, source_word_count, primary_source_chapter_url, content_file_path
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ? AND status IN ('processed', 'fallback') AND chapter_index >= ?
            ORDER BY chapter_index ASC
            LIMIT 3
            """,
            (book["aggregateBookId"], max(1, args.start_chapter_index)),
        ).fetchall()
        if not processed_sample:
            processed_sample = conn.execute(
                """
                SELECT chapter_index, title, status, preview_only, source_word_count, primary_source_chapter_url, content_file_path
                FROM aggregate_chapter_tasks
                WHERE aggregate_book_id = ? AND status IN ('processed', 'fallback')
                ORDER BY chapter_index ASC
                LIMIT 3
                """,
                (book["aggregateBookId"],),
            ).fetchall()

    output = {
        "dbPath": str(db_path),
        "tempDir": str(temp_dir) if temp_dir else "",
        "admin": admin_info,
        "actor": actor_info,
        "baselineCounts": baseline_counts,
        "deletedExisting": deleted_existing or {},
        "realAiEnabled": bool(args.real_ai),
        "enqueue": enqueue,
        "subscription": subscription,
        "subscriptionCreated": subscription_created,
        "rounds": results,
        "summary": summary,
        "chapterSample": [
            {
                "chapterIndex": row[0],
                "title": row[1],
                "status": row[2],
                "previewOnly": bool(row[3]),
                "sourceWordCount": int(row[4] or 0),
                "primarySourceChapterUrl": row[5] or "",
                "contentFilePath": row[6] or "",
            }
            for row in chapter_sample
        ],
        "processedSample": [
            {
                "chapterIndex": row[0],
                "title": row[1],
                "status": row[2],
                "previewOnly": bool(row[3]),
                "sourceWordCount": int(row[4] or 0),
                "primarySourceChapterUrl": row[5] or "",
                "contentFilePath": row[6] or "",
                "fileInspection": inspect_chapter_file(row[6] or ""),
            }
            for row in processed_sample
        ],
        "readingContract": inspect_reading_contract(service, book["aggregateBookId"]),
        "rollbackCreated": bool(args.rollback_created),
    }

    if args.rollback_created:
        with sqlite3.connect(db_path) as conn:
            delete_aggregate_book(conn, book["aggregateBookId"])
            if args.rollback_created_admin and created_admin_user_id:
                delete_user(conn, created_admin_user_id)
            output["postRollbackCounts"] = db_counters(conn)

    print(json.dumps(output, ensure_ascii=False, indent=2))

    if temp_dir and not args.keep_temp_db:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
