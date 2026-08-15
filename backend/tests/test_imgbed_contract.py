from __future__ import annotations
import asyncio
from app.services.imgbed import ImgBedConfig, ImgBedUploader

class Response:
    status_code=200
    is_error=False
    content=b'[{"src":"/file/test.jpg","publicUrl":"https://img.xzaiweb.me/file/test.jpg"}]'
    def json(self): return [{"src":"/file/test.jpg","publicUrl":"https://img.xzaiweb.me/file/test.jpg"}]
    def raise_for_status(self): pass

class Client:
    last_kwargs=None
    def __init__(self,*_args,**kwargs): self.kwargs=kwargs
    async def __aenter__(self): return self
    async def __aexit__(self,*_args): pass
    async def post(self,url,**kwargs): Client.last_kwargs=(url,kwargs); return Response()

def test_xz_image_headers_and_public_url(monkeypatch):
    import app.services.imgbed as mod
    monkeypatch.setattr(mod.httpx,"AsyncClient",Client)
    uploader=ImgBedUploader(ImgBedConfig(enabled_setting=True,base_url="https://img.xzaiweb.me",api_token="token",upload_channel="cfr2",channel_name="R2_env",upload_folder="imgbed"))
    result=asyncio.run(uploader.upload(b"\xff\xd8\xfffake",mime_type="image/jpeg",filename="a.jpg"))
    assert result == "https://img.xzaiweb.me/file/test.jpg"
    url,kwargs=Client.last_kwargs
    assert url == "https://img.xzaiweb.me/upload"
    assert kwargs["headers"]["channelName"] == "R2_env"
    assert kwargs["headers"]["uploadFolder"] == "/imgbed"
    assert kwargs["headers"]["returnFormat"] == "full"
    assert kwargs["headers"]["Authorization"] == "Bearer token"
    assert kwargs["params"] == {}
