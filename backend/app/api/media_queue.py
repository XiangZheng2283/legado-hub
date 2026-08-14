"""Administrator API for the fanqie media upload queue."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from app.services.user_auth import auth_service
from app.services.media_upload_queue import media_upload_queue_service

router=APIRouter(prefix="/api/admin/media-queue", dependencies=[Depends(auth_service.require_admin)])

@router.get("")
def list_queue(limit:int=100,offset:int=0,book_id:str="",status:str=""):
    return {"items":media_upload_queue_service.list(limit=limit,offset=offset,book_id=book_id,status=status)}
@router.get("/stats")
def stats(): return media_upload_queue_service.stats()
@router.post("/{item_id}/retry")
def retry(item_id:int):
    if not media_upload_queue_service.retry(item_id): raise HTTPException(404,"队列项不存在或不可重试")
    return {"ok":True}
@router.post("/retry-failed")
def retry_failed(): return {"ok":True,"count":media_upload_queue_service.retry_failed()}
@router.delete("/{item_id}")
def delete(item_id:int):
    if not media_upload_queue_service.delete(item_id): raise HTTPException(404,"队列项不存在")
    return {"ok":True}
@router.post("/book/{book_id}/enqueue")
def enqueue_book(book_id:str,payload:dict[str,Any]):
    save_dir=str(payload.get("saveDir") or "").strip()
    if not save_dir: raise HTTPException(422,"saveDir 必填")
    return {"ids":media_upload_queue_service.enqueue_book(book_id,save_dir)}
@router.post("/avatars")
def enqueue_avatars(payload:dict[str,Any]):
    book_id=str(payload.get("bookId") or "").strip(); save_dir=str(payload.get("saveDir") or "").strip(); urls=payload.get("sourceUrls")
    if not book_id or not save_dir or not isinstance(urls,list): raise HTTPException(422,"bookId、saveDir、sourceUrls 必填")
    return {"ids":[i for url in urls if (i:=media_upload_queue_service.enqueue_ref(book_id,save_dir,"avatar",str(url)))]}
@router.get("/book/{book_id}/chapters/{chapter_id}/avatars")
def avatars(book_id:str,chapter_id:str,save_dir:str):
    root=Path(save_dir).expanduser().resolve(); chapter_name=Path(str(chapter_id)).name; path=root/book_id/"segment_comments"/(chapter_name+".json")
    if not path.is_file(): return {"items":[]}
    try: data=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return {"items":[]}
    found=[]; seen=set()
    def walk(value):
        if isinstance(value,dict):
            user=value.get("user") if isinstance(value.get("user"),dict) else value
            url=str(user.get("avatar") or "").strip() if isinstance(user,dict) else ""
            if url and url not in seen:
                seen.add(url); digest=hashlib.sha1(url.encode()).hexdigest()
                local=next((root/book_id/"images"/(digest+ext) for ext in (".jpeg",".jpg",".png",".gif",".webp") if (root/book_id/"images"/(digest+ext)).is_file()),None)
                if local: found.append({"userName":str(user.get("name") or user.get("user_name") or ""),"sourceUrl":url,"ref":"OEBPS/images/"+local.name,"alreadyUploadedUrl":media_upload_queue_service.find_uploaded(source_url=url)})
            for child in value.values(): walk(child)
        elif isinstance(value,list):
            for child in value: walk(child)
    walk(data); return {"items":found}
