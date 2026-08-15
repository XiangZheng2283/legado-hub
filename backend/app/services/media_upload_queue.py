"""Persistent, local-file-only ImgBed upload queue."""
from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from app.config import DB_PATH
from app.services.imgbed import ImgBedUploadError, get_imgbed_uploader, is_trusted_imgbed_url, sniff_image_mime
from app.storage.db import initialize_database

STATUSES = ("queued", "uploading", "done", "failed", "rate_limited")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _retry_seconds(value: str, default: int = 60) -> int:
    try:
        return max(1, min(86400, int(value.strip())))
    except (TypeError, ValueError):
        pass
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(1, min(86400, int((parsed - _now()).total_seconds())))
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_path(root: Path, value: str | Path) -> Path | None:
    try:
        base = root.expanduser().resolve()
        candidate = Path(value).expanduser().resolve()
        candidate.relative_to(base)
        return candidate
    except (OSError, ValueError):
        return None


def _asset_key(kind: str, source_url: str, path: Path) -> str:
    if source_url:
        return "url:" + hashlib.sha1(source_url.encode("utf-8")).hexdigest()
    return f"{kind}:" + path.stem.lower()


def _ref_for(path: Path, kind: str) -> str:
    if kind == "cover":
        return "cover.jpg"
    return "OEBPS/images/" + path.name


class MediaUploadQueueService:
    def __init__(self, db_path: Path | str | None = None, *, concurrency: int = 4):
        self.db_path = Path(db_path or DB_PATH)
        self.concurrency = max(1, min(32, int(concurrency)))
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._running = 0
        initialize_database(self.db_path)
        self.reset_stale_uploading()
        self.prune_comment_media()

    def prune_comment_media(self) -> int:
        """评论头像/评论图像已改为经 images/ 本地映射返回，不再走上传队列。

        清掉历史遗留的 content/avatar 项（即便已 done 也不再需要），并配合
        _claim 只认 kind='cover'，确保评论媒体在任何情况下都不会被上传。
        """
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM media_upload_queue WHERE kind IN ('content','avatar')"
            )
            conn.commit()
            return cur.rowcount

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def reset_stale_uploading(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("UPDATE media_upload_queue SET status='queued', updated_at=datetime('now') WHERE status='uploading'")
            conn.commit()
            return cur.rowcount

    def enqueue_file(self, book_id: str, local_path: str | Path, *, kind: str, source_url: str = "", ref: str = "", save_dir: str | Path | None = None) -> int | None:
        if kind not in {"avatar", "content", "cover"}:
            raise ValueError("invalid media kind")
        path = Path(local_path).expanduser().resolve()
        root = Path(save_dir).expanduser().resolve() if save_dir else path.parent.parent
        if _safe_path(root, path) is None or not path.is_file():
            return None
        if kind == "cover" and path.name.lower() not in {"cover.jpg", "cover.jpeg", "cover.png", "cover.webp"}:
            return None
        if kind == "cover":
            try:
                key = "cover:" + hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                return None
        else:
            key = _asset_key(kind, source_url.strip(), path)
        clean_ref = ref.strip() or _ref_for(path, kind)
        with self._connect() as conn:
            row = conn.execute("SELECT id, status FROM media_upload_queue WHERE asset_key=?", (key,)).fetchone()
            if row:
                if row[1] in {"failed", "rate_limited"}:
                    conn.execute("UPDATE media_upload_queue SET local_path=?, book_id=?, kind=?, source_url=?, ref=?, status='queued', error=NULL, next_retry_at=NULL, updated_at=datetime('now') WHERE id=?", (str(path), str(book_id), kind, source_url.strip() or None, clean_ref, row[0]))
                    conn.commit(); self._wake.set()
                return int(row[0])
            cur = conn.execute("INSERT INTO media_upload_queue(book_id,kind,source_url,local_path,ref,asset_key) VALUES(?,?,?,?,?,?)", (str(book_id), kind, source_url.strip() or None, str(path), clean_ref, key))
            conn.commit(); self._wake.set(); return int(cur.lastrowid)

    def enqueue_book(self, book_id: str, save_dir: str | Path) -> list[int]:
        root = Path(save_dir).expanduser().resolve()
        result: list[int] = []
        # 评论头像 / 评论图像不再于下载完成后自动上传到图床：它们改由 hub 按
        # fqdown 的 sha1(url) 映射读本地 images/ 缓存（/api/legado/media/...）
        # 直接返回客户端，不入上传队列、不上传 url。这里只把封面交给 img 上传。
        # （enqueue_file/enqueue_ref 等方法保留，供显式/其它用途调用。）
        for name in ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp"):
            path = root / name
            if path.is_file():
                item = self.enqueue_file(book_id, path, kind="cover", ref="cover.jpg", save_dir=root)
                if item is not None: result.append(item); break
        return result

    def enqueue_ref(self, book_id: str, save_dir: str | Path, kind: str, source_url: str, *, ref: str = "") -> int | None:
        if not source_url or kind not in {"avatar", "content"}:
            return None
        digest = hashlib.sha1(source_url.strip().encode("utf-8")).hexdigest()
        root = Path(save_dir).expanduser().resolve()
        images = root / "images"
        for ext in (".jpeg", ".jpg", ".png", ".gif", ".webp"):
            path = images / (digest + ext)
            if path.is_file():
                return self.enqueue_file(book_id, path, kind=kind, source_url=source_url, ref=ref or _ref_for(path, kind), save_dir=root)
        return None

    def get(self, item_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM media_upload_queue WHERE id=?", (item_id,)).fetchone()
            return dict(row) if row else None

    def find_cover(self, book_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT uploaded_url FROM media_upload_queue WHERE book_id=? AND kind='cover' AND status='done' LIMIT 1", (str(book_id),)).fetchone()
            url = str(row[0] or "") if row else ""
            return url if is_trusted_imgbed_url(url) else ""

    def find_uploaded(self, *, ref: str = "", source_url: str = "", asset_key: str = "") -> str:
        keys = []
        if asset_key: keys.append(asset_key)
        if source_url: keys.append(_asset_key("content", source_url, Path("asset")))
        with self._connect() as conn:
            row = None
            if keys: row = conn.execute("SELECT uploaded_url FROM media_upload_queue WHERE asset_key=? AND status='done' LIMIT 1", (keys[0],)).fetchone()
            if not row and ref: row = conn.execute("SELECT uploaded_url FROM media_upload_queue WHERE ref=? AND status='done' LIMIT 1", (ref,)).fetchone()
            url = str(row[0] or "") if row else ""
            return url if is_trusted_imgbed_url(url) else ""

    def list(self, *, limit: int = 100, offset: int = 0, book_id: str = "", status: str = "") -> list[dict[str, Any]]:
        clauses=[]; params=[]
        if book_id: clauses.append("book_id=?"); params.append(book_id)
        if status in STATUSES: clauses.append("status=?"); params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as conn:
            rows=conn.execute(f"SELECT id,book_id,kind,source_url,ref,status,attempts,retry_after_seconds,next_retry_at,uploaded_url,error,created_at,updated_at FROM media_upload_queue{where} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, max(1,min(500,limit)), max(0,offset))).fetchall()
            return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        result={s:0 for s in STATUSES}
        with self._connect() as conn:
            for row in conn.execute("SELECT status,COUNT(*) n FROM media_upload_queue GROUP BY status").fetchall(): result[str(row[0])] = int(row[1])
        result["concurrency"] = self.concurrency; result["active"] = self._running; result["currentConcurrency"] = self._running
        return result

    def retry(self, item_id: int) -> bool:
        with self._connect() as conn:
            cur=conn.execute("UPDATE media_upload_queue SET status='queued',error=NULL,next_retry_at=NULL,updated_at=datetime('now') WHERE id=? AND status IN ('failed','rate_limited')",(item_id,)); conn.commit()
        self._wake.set(); return cur.rowcount > 0

    def retry_failed(self) -> int:
        with self._connect() as conn:
            cur=conn.execute("UPDATE media_upload_queue SET status='queued',error=NULL,next_retry_at=NULL,updated_at=datetime('now') WHERE status IN ('failed','rate_limited')"); conn.commit()
        self._wake.set(); return cur.rowcount

    def delete(self, item_id: int) -> bool:
        with self._connect() as conn:
            cur=conn.execute("DELETE FROM media_upload_queue WHERE id=?",(item_id,)); conn.commit(); return cur.rowcount > 0

    def _claim(self) -> dict[str, Any] | None:
        now=_iso(_now())
        with self._connect() as conn:
            row=conn.execute("SELECT * FROM media_upload_queue WHERE kind='cover' AND (status='queued' OR (status='rate_limited' AND (next_retry_at IS NULL OR next_retry_at<=?))) ORDER BY id LIMIT 1",(now,)).fetchone()
            if not row: return None
            cur=conn.execute("UPDATE media_upload_queue SET status='uploading',attempts=attempts+1,updated_at=datetime('now') WHERE id=? AND status IN ('queued','rate_limited')",(row["id"],)); conn.commit()
            return dict(row) if cur.rowcount else None

    async def _upload_one(self, item: dict[str, Any]) -> None:
        item_id=int(item["id"]); path=Path(str(item["local_path"]))
        try:
            data=await asyncio.to_thread(path.read_bytes)
            mime=sniff_image_mime(data) or mimetypes.guess_type(path.name)[0] or ""
            if mime not in {"image/jpeg","image/png","image/gif","image/webp"}: raise ValueError("unsupported local image")
            url=await get_imgbed_uploader().upload(data,mime_type=mime,filename=path.name)
            if not url or not is_trusted_imgbed_url(url): raise ValueError("ImgBed returned no trusted https URL")
            with self._connect() as conn: conn.execute("UPDATE media_upload_queue SET status='done',uploaded_url=?,error=NULL,next_retry_at=NULL,updated_at=datetime('now') WHERE id=?",(url,item_id)); conn.commit()
        except ImgBedUploadError as exc:
            if exc.status_code == 429:
                delay=_retry_seconds(exc.retry_after, 60)
                with self._connect() as conn: conn.execute("UPDATE media_upload_queue SET status='rate_limited',retry_after_seconds=?,next_retry_at=?,error=?,updated_at=datetime('now') WHERE id=?",(delay,_iso(_now()+timedelta(seconds=delay)),"429 rate limited",item_id)); conn.commit()
            else:
                with self._connect() as conn: conn.execute("UPDATE media_upload_queue SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",(str(exc)[:500],item_id)); conn.commit()
        except Exception as exc:
            with self._connect() as conn: conn.execute("UPDATE media_upload_queue SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",(str(exc)[:500],item_id)); conn.commit()

    async def run_once(self) -> bool:
        item=self._claim()
        if not item: return False
        self._running += 1
        try: await self._upload_one(item)
        finally: self._running -= 1
        return True

    async def run_forever(self, stop_event: asyncio.Event | None = None, *, poll_seconds: float = 1.0) -> None:
        stop=stop_event or self._stop
        while not stop.is_set():
            jobs=[asyncio.create_task(self.run_once()) for _ in range(self.concurrency)]
            results=await asyncio.gather(*jobs)
            if not any(results):
                try: await asyncio.wait_for(self._wake.wait(), timeout=poll_seconds)
                except asyncio.TimeoutError: pass
                self._wake.clear()

    def stop(self) -> None: self._stop.set()

media_upload_queue_service = MediaUploadQueueService()
