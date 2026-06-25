"""Filesystem cache for readable novel chapter files.

Directory layout:
- Subscription books (source_id == "legadohub_ai_aggregate"):
    data/novels/legadohub_ai_aggregate/{书名}_{作者}/
        ├── metadata.json
        ├── 000001 第一章.md
        └── ...
- Third-party source caches (everything else):
    data/novels/{source-domain}/{encoded-book-key}/
        └── ...
  These folders are temporary and can be cleaned up by a periodic job.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import DATA_DIR

RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

SUBSCRIPTION_SOURCE_ID = "legadohub_ai_aggregate"
SUBSCRIPTION_FOLDER = "legadohub"
METADATA_FILE = "metadata.json"


class NovelFileCache:
    """Write chapter content under data/novels/source-domain/book-folder."""

    def __init__(self, root: Path | None = None):
        self.root = root or DATA_DIR / "novels"

    def write_chapter(
        self,
        *,
        conn: sqlite3.Connection,
        chapter_id: str,
        source_id: str,
        chapter_url: str,
        title: str,
        content: str,
        book_id: str = "",
        book_name: str = "",
        author: str = "",
        chapter_index: int | None = None,
        trace_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not content:
            return {"written": False, "reason": "empty content"}

        context = self._chapter_context(
            conn,
            chapter_id=chapter_id,
            chapter_url=chapter_url,
            fallback_book_id=book_id,
            fallback_book_name=book_name,
            fallback_chapter_title=title,
            fallback_chapter_index=chapter_index,
        )
        source_folder = self._source_folder(source_id, chapter_url)
        book_folder = self._book_folder(
            source_id=source_id,
            book_id=book_id or context["bookId"],
            book_name=context["bookName"] or book_name,
            author=author,
            chapter_url=chapter_url,
        )
        chapter_title = context["chapterTitle"] or title or "未命名章节"
        chapter_number = context["chapterIndex"]
        file_stem = self._chapter_file_stem(chapter_number, chapter_title)
        target_dir = self.root / source_folder / book_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{file_stem}.md"
        text = self._markdown_content(chapter_title, content, trace_meta=trace_meta or {})
        target_path.write_text(text, encoding="utf-8", newline="\n")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        if source_id == SUBSCRIPTION_SOURCE_ID:
            self._write_subscription_metadata(
                target_dir,
                book_id=book_id or context["bookId"],
                book_name=context["bookName"] or book_name,
                author=author,
            )

        return {
            "written": True,
            "bookId": context["bookId"] or book_id,
            "bookName": context["bookName"] or book_name,
            "chapterTitle": chapter_title,
            "chapterIndex": chapter_number,
            "filePath": str(target_path),
            "contentHash": content_hash,
        }

    def _chapter_context(
        self,
        conn: sqlite3.Connection,
        *,
        chapter_id: str,
        chapter_url: str,
        fallback_book_id: str = "",
        fallback_book_name: str = "",
        fallback_chapter_title: str = "",
        fallback_chapter_index: int | None = None,
    ) -> dict[str, Any]:
        context = {
            "bookId": fallback_book_id,
            "bookName": fallback_book_name,
            "chapterTitle": fallback_chapter_title,
            "chapterIndex": fallback_chapter_index,
        }
        try:
            toc_rows = conn.execute("SELECT book_id, response_json FROM toc_cache").fetchall()
        except sqlite3.OperationalError:
            toc_rows = []
        for book_id, response_json in toc_rows:
            try:
                payload = json.loads(response_json or "{}")
            except Exception:
                continue
            chapters = payload.get("chapters") if isinstance(payload.get("chapters"), list) else []
            for index, chapter in enumerate(chapters, start=1):
                if not isinstance(chapter, dict):
                    continue
                cached_chapter_url = chapter.get("chapterUrl", "")
                if (
                    chapter.get("chapterId") != chapter_id
                    and cached_chapter_url != chapter_url
                    and not str(cached_chapter_url).rstrip("/").endswith(f"/{chapter_id}")
                ):
                    continue
                context["bookId"] = context["bookId"] or book_id
                context["chapterTitle"] = context["chapterTitle"] or chapter.get("title", "")
                context["chapterIndex"] = context["chapterIndex"] or int(chapter.get("index") or index)
                break
            if context["bookId"] == book_id and context["chapterIndex"]:
                break

        if context["bookId"] and not context["bookName"]:
            context["bookName"] = self._book_name(conn, context["bookId"])
        return context

    def _book_name(self, conn: sqlite3.Connection, book_id: str) -> str:
        try:
            row = conn.execute("SELECT response_json FROM book_cache WHERE book_id = ?", (book_id,)).fetchone()
            if row:
                try:
                    payload = json.loads(row[0] or "{}")
                    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                    name = data.get("name", "") if isinstance(data, dict) else ""
                    if name:
                        return name
                except Exception:
                    pass
            row = conn.execute("SELECT name FROM book_records WHERE book_id = ?", (book_id,)).fetchone()
            return row[0] if row and row[0] else ""
        except sqlite3.OperationalError:
            return ""

    def _source_folder(self, source_id: str, chapter_url: str) -> str:
        if source_id == SUBSCRIPTION_SOURCE_ID:
            return self._safe_segment(SUBSCRIPTION_FOLDER)
        parsed = urlparse(chapter_url or "")
        host = parsed.netloc.lower()
        if "@" in host:
            host = host.rsplit("@", 1)[-1]
        if ":" in host:
            host = host.split(":", 1)[0]
        return self._safe_segment(host or source_id or "unknown-source")

    def _book_folder(
        self,
        *,
        source_id: str,
        book_id: str,
        book_name: str,
        author: str,
        chapter_url: str,
    ) -> str:
        if source_id == SUBSCRIPTION_SOURCE_ID:
            name = self._safe_segment(book_name or "unknown-book", max_length=80)
            author_part = self._safe_segment(author or "", max_length=40)
            if author_part:
                return f"{name}_{author_part}"
            return name

        # Third-party caches use an opaque encoded key so they stay temporary
        # and can be safely cleaned up without colliding with subscription books.
        key = book_id or f"{source_id}:{chapter_url}"
        if not key:
            return "unknown-book"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def _write_subscription_metadata(
        self,
        book_dir: Path,
        *,
        book_id: str,
        book_name: str,
        author: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        metadata_path = book_dir / METADATA_FILE
        now = datetime.now(timezone.utc).isoformat()
        existing: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

        chapter_files = sorted(
            p for p in book_dir.glob("*.md") if p.is_file() and p.name != METADATA_FILE
        )

        metadata: dict[str, Any] = {
            "bookId": book_id or existing.get("bookId", ""),
            "bookName": book_name or existing.get("bookName", ""),
            "author": author or existing.get("author", ""),
            "sourceId": SUBSCRIPTION_SOURCE_ID,
            "createdAt": existing.get("createdAt") or now,
            "updatedAt": now,
            "chapterCount": len(chapter_files),
        }
        # Merge persistent extra fields (cover, primary source, etc.) so the
        # directory can be rebuilt on a fresh start without the database.
        for key, value in (extra or {}).items():
            if key not in ("bookId", "bookName", "author", "sourceId", "createdAt", "updatedAt", "chapterCount"):
                metadata[key] = value

        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def cleanup_temp_cache(
        self,
        *,
        max_age_hours: int = 24,
        dry_run: bool = False,
    ) -> list[Path]:
        """Remove third-party source cache folders older than max_age_hours.

        Subscription books under legadohub_ai_aggregate are never touched.
        """
        removed: list[Path] = []
        if not self.root.exists():
            return removed

        now = datetime.now(timezone.utc)
        cutoff = max_age_hours * 3600

        for source_dir in self.root.iterdir():
            if not source_dir.is_dir():
                continue
            if source_dir.name == self._safe_segment(SUBSCRIPTION_FOLDER):
                continue
            for book_dir in source_dir.iterdir():
                if not book_dir.is_dir():
                    continue
                try:
                    mtime = book_dir.stat().st_mtime
                    mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
                    if (now - mtime_dt).total_seconds() > cutoff:
                        if not dry_run:
                            import shutil

                            shutil.rmtree(book_dir, ignore_errors=True)
                        removed.append(book_dir)
                except Exception:
                    continue
        return removed

    def _safe_segment(self, value: str, max_length: int = 96) -> str:
        value = str(value or "").strip().strip(".")
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value)
        value = re.sub(r"\s+", " ", value).strip()
        if not value:
            value = "unknown"
        if value.upper() in RESERVED_WINDOWS_NAMES:
            value = f"{value}_"
        return value[:max_length].rstrip(" .") or "unknown"

    def _chapter_file_stem(self, index: int | None, title: str) -> str:
        safe_title = self._safe_segment(title or "未命名章节", max_length=120)
        if index and index > 0:
            return f"{index:06d} {safe_title}"
        return safe_title

    def _markdown_content(self, title: str, content: str, trace_meta: dict[str, Any] | None = None) -> str:
        body = str(content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        heading = str(title or "").strip()
        text = body
        if heading and not body.startswith(f"# {heading}"):
            text = f"# {heading}\n\n{body}"
        trace_block = self._trace_block(trace_meta or {})
        if trace_block:
            return f"{text}\n\n{trace_block}\n"
        return f"{text}\n"

    def _trace_block(self, trace_meta: dict[str, Any]) -> str:
        if not trace_meta:
            return ""
        yaml_lines = [
            "LEGADOHUB_TRACE_BEGIN",
            "```yaml",
        ]
        yaml_lines.extend(self._yaml_lines(trace_meta))
        yaml_lines.extend(
            [
                "```",
                "LEGADOHUB_TRACE_END",
            ]
        )
        return "\n".join(yaml_lines)

    def _yaml_lines(self, value: Any, indent: int = 0) -> list[str]:
        prefix = "  " * indent
        if isinstance(value, dict):
            lines: list[str] = []
            for key, item in value.items():
                if isinstance(item, (dict, list)):
                    lines.append(f"{prefix}{key}:")
                    lines.extend(self._yaml_lines(item, indent + 1))
                else:
                    lines.append(f"{prefix}{key}: {self._yaml_scalar(item)}")
            return lines
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if isinstance(item, (dict, list)):
                    lines.append(f"{prefix}-")
                    lines.extend(self._yaml_lines(item, indent + 1))
                else:
                    lines.append(f"{prefix}- {self._yaml_scalar(item)}")
            return lines
        return [f"{prefix}{self._yaml_scalar(value)}"]

    def _yaml_scalar(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).replace("\r\n", "\\n").replace("\n", "\\n")
        if text == "":
            return '""'
        if any(ch in text for ch in [":", "#", "{", "}", "[", "]", ",", '"', "'"]):
            text = text.replace('"', '\\"')
            return f'"{text}"'
        return text
