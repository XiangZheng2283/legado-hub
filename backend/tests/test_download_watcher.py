import asyncio
from pathlib import Path
from app.services.download_watcher import DownloadWatcher

class Response:
    def __init__(self,p): self.p=p
    def json(self): return self.p
class Client:
    def __init__(self,*a,**kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self,*a): pass
    async def get(self,url,**kw):
        return Response({"items":[{"book_id":"b1","state":"done"}]}) if url.endswith("/jobs") else Response({"save_dir":str(ROOT)})
class Queue:
    def __init__(self): self.calls=[]
    def enqueue_book(self,book_id,path): self.calls.append((book_id,Path(path))); return [1]

def test_done_job_is_enqueued_once(tmp_path,monkeypatch):
    global ROOT; ROOT=tmp_path; book=tmp_path/"b1"; (book/"images").mkdir(parents=True); (book/"images"/("a"*40+".jpg")).write_bytes(b"x"); (book/"cover.jpg").write_bytes(b"x")
    import app.services.download_watcher as mod
    monkeypatch.setattr(mod.httpx,"AsyncClient",Client)
    q=Queue(); watcher=DownloadWatcher(q,base_url="http://downloader",db_path=tmp_path/"db.sqlite")
    assert asyncio.run(watcher.poll_once()) == ["b1"]
    assert asyncio.run(watcher.poll_once()) == []
    assert q.calls == [("b1",book)]
