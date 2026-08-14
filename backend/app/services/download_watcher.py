"""Poll Tomato downloader jobs and enqueue completed books."""
from __future__ import annotations
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import httpx
from app.config import DB_PATH
from app.services.media_upload_queue import MediaUploadQueueService
from app.storage.db import initialize_database

class DownloadWatcher:
    def __init__(self, queue: MediaUploadQueueService | None = None, *, base_url: str | None = None, interval_seconds: float = 10.0, db_path: Path | str | None = None):
        self.queue=queue or MediaUploadQueueService(db_path=db_path)
        self.base_url=(base_url or os.environ.get("FANQIE_LOCAL_BASE","http://127.0.0.1:18423")).rstrip("/")
        self.interval_seconds=max(2.0,float(interval_seconds)); self.db_path=Path(db_path or DB_PATH); initialize_database(self.db_path)
    def _seen(self, book_id: str) -> bool:
        with sqlite3.connect(self.db_path) as c: return c.execute("SELECT 1 FROM media_upload_watcher WHERE book_id=?",(book_id,)).fetchone() is not None
    def _mark(self, book_id: str) -> None:
        with sqlite3.connect(self.db_path) as c: c.execute("INSERT OR REPLACE INTO media_upload_watcher(book_id,completed_at,updated_at) VALUES(?,?,datetime('now'))",(book_id,datetime.now(timezone.utc).isoformat())); c.commit()
    async def poll_once(self) -> list[str]:
        headers={"Accept":"application/json"}; password=os.environ.get("FANQIE_LOCAL_PASSWD","")
        if password: headers["x-tomato-password"]=password
        async with httpx.AsyncClient(timeout=10) as client:
            jobs=(await client.get(f"{self.base_url}/api/jobs",params={"all":"true"},headers=headers)).json()
            status=(await client.get(f"{self.base_url}/api/status",headers=headers)).json()
        save_dir=str(status.get("save_dir") or "").strip()
        if not save_dir: return []
        done=[]
        for job in jobs.get("items",[]) if isinstance(jobs,dict) else []:
            book_id=str(job.get("book_id") or "").strip()
            if book_id and str(job.get("state") or "").lower()=="done" and not self._seen(book_id):
                self.queue.enqueue_book(book_id,Path(save_dir)/book_id); self._mark(book_id); done.append(book_id)
        return done
    async def run_forever(self, stop_event):
        while not stop_event.is_set():
            try: await self.poll_once()
            except Exception: pass
            try: await __import__('asyncio').wait_for(stop_event.wait(),timeout=self.interval_seconds)
            except __import__('asyncio').TimeoutError: pass
