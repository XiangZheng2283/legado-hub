from __future__ import annotations
import asyncio
from pathlib import Path
from app.services import media_upload_queue as queue_mod
from app.services.imgbed import ImgBedUploadError

def _jpeg(): return b"\xff\xd8\xff\xe0fake"

def test_enqueue_book_deduplicates_and_uploads(tmp_path, monkeypatch):
    root=tmp_path/"book"; (root/"images").mkdir(parents=True); (root/"images"/("a"*40+".jpg")).write_bytes(_jpeg()); (root/"cover.jpg").write_bytes(_jpeg())
    class Uploader:
        async def upload(self,*_args,**_kwargs): return "https://imgbed.example/a"
    monkeypatch.setattr(queue_mod,"get_imgbed_uploader",lambda:Uploader())
    monkeypatch.setattr(queue_mod,"is_trusted_imgbed_url",lambda _url: True)
    service=queue_mod.MediaUploadQueueService(tmp_path/"q.db",concurrency=1)
    assert len(service.enqueue_book("b",root))==2
    assert len(service.enqueue_book("b",root))==2
    async def run():
        while await service.run_once(): pass
    asyncio.run(run())
    assert service.stats()["done"]==2

def test_rate_limit_uses_retry_after(tmp_path, monkeypatch):
    root=tmp_path/"book"; (root/"images").mkdir(parents=True); path=root/"images"/("b"*40+".png"); path.write_bytes(b"\x89PNG\r\n\x1a\nbody")
    class Uploader:
        async def upload(self,*_args,**_kwargs): raise ImgBedUploadError("429",status_code=429,retry_after="120")
    monkeypatch.setattr(queue_mod,"get_imgbed_uploader",lambda:Uploader())
    monkeypatch.setattr(queue_mod,"is_trusted_imgbed_url",lambda _url: True)
    service=queue_mod.MediaUploadQueueService(tmp_path/"q.db",concurrency=1); service.enqueue_book("b",root); asyncio.run(service.run_once())
    item=service.list()[0]; assert item["status"]=="rate_limited"; assert item["retry_after_seconds"]==120; assert item["next_retry_at"]

def test_stale_uploading_is_reset(tmp_path):
    service=queue_mod.MediaUploadQueueService(tmp_path/"q.db")
    with service._connect() as conn:
        conn.execute("INSERT INTO media_upload_queue(book_id,kind,local_path,ref,asset_key,status) VALUES('b','content','x','r','x','uploading')"); conn.commit()
    assert service.reset_stale_uploading()==1
    assert service.list()[0]["status"]=="queued"
