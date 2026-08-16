"""Legado-facing endpoints for shared library book/toc/chapter access.

The old aggregate search/explore/source endpoints were removed; only the
book reader contract remains, backed by the shared library storage.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.services.catalog import Catalog
from app.services.library_books import format_reading_update_time, library_books_service
from app.services.aggregate_virtual_source import (
    VIRTUAL_SOURCE_ID,
    make_aggregate_chapter_url,
    unpack_aggregate_book_url,
    unpack_aggregate_chapter_url,
)
from app.source_plugins.id_codec import (
    decode_book_id,
    decode_chapter_id,
    encode_book_id,
    encode_chapter_id,
)
from app.services.fanqie_local_trigger import get_save_dir, spawn_fanqie_trigger_for_url
from app.services.chapter_review_catalog import _enrich_review_media
from app.services.reading_reviews import (
    chapter_review_cache,
    render_chapter_reviews_html,
)
from app.services.user_auth import auth_service
from app.core.public_security import get_public_base_url
from app.services.reading_limits import reading_access_limiter

router = APIRouter(prefix="/api/legado")
logger = logging.getLogger(__name__)
_EXTERNAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+:[A-Za-z0-9_-]+$")
_MAX_EXTERNAL_ID_LENGTH = 8192
_MAX_NUMERIC_ID = 2**63 - 1


def _validated_external_id(value: str, *, label: str) -> str:
    normalized = str(value or "")
    if (
        not normalized
        or len(normalized) > _MAX_EXTERNAL_ID_LENGTH
        or not _EXTERNAL_ID_PATTERN.fullmatch(normalized)
    ):
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    return normalized


def _reject_query_anomalies(request: Request, allowed: set[str]) -> None:
    unknown = set(request.query_params.keys()) - allowed
    repeated = {key for key in allowed if len(request.query_params.getlist(key)) > 1}
    if unknown or repeated:
        raise HTTPException(status_code=422, detail="查询参数无效")


def _query_int(
    value: str | None,
    *,
    field: str,
    minimum: int,
    maximum: int,
    default: int | None = None,
) -> int | None:
    if value is None or value == "":
        return default
    if not value.isascii() or not value.isdigit():
        if not (minimum < 0 and value.startswith("-") and value[1:].isascii() and value[1:].isdigit()):
            raise HTTPException(status_code=422, detail=f"{field} 必须是整数")
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise HTTPException(status_code=422, detail=f"{field} 超出允许范围")
    return parsed


def _decode_book_identity(book_id: str) -> tuple[str, str]:
    try:
        return decode_book_id(book_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="书籍不存在") from exc


def _decode_chapter_identity(chapter_id: str) -> tuple[str, str]:
    try:
        return decode_chapter_id(chapter_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="章节不存在") from exc


def _kick_fanqie_for_aggregate(aggregate_book_id: str) -> None:
    """Fire-and-forget start the fanqie_local downloader for an aggregate book.

    Reading (detail / toc / chapter body) before the fanqie output exists must
    kick the whole-book job so the incremental files (cover /
    downloaded_chapters.jsonl / segment_comments / images) start producing.
    Otherwise the reader 404s on "尚未发布" forever because nothing told the
    downloader to fetch. Never blocks the response and never raises.
    """
    if not aggregate_book_id:
        return
    try:
        book = library_books_service.get_book(aggregate_book_id)
    except Exception:
        return
    if not book or str(book.get("primarySourceId") or "") != "fanqie_local":
        return
    primary_url = str(book.get("primaryBookUrl") or "")
    if primary_url:
        spawn_fanqie_trigger_for_url(primary_url)


def _kick_fanqie_for_aggregate_and(aggregate_book_id: str, fanqie_book_id: str) -> None:
    """Kick the fanqie download when the aggregate book isn't shared yet.

    Tries the shared-book primary source first, then falls back to spawning the
    trigger straight from the resolved fanqie book id (covers the case where no
    shared library row exists yet). Never raises.
    """
    try:
        _kick_fanqie_for_aggregate(aggregate_book_id)
    except Exception:
        pass
    try:
        _source, url = decode_book_id(fanqie_book_id)
        if url:
            spawn_fanqie_trigger_for_url(url)
    except Exception:
        pass


def _kick_fanqie_on_missing_chapter(chapter_id: str, chapter_url: str) -> None:
    """Resolve the aggregate book behind a not-yet-published chapter and kick
    the fanqie download (see _kick_fanqie_for_aggregate). Never raises."""
    try:
        payload = unpack_aggregate_chapter_url(chapter_url)
        aggregate_book_id = str(payload.get("aggregateBookId") or "")
    except Exception:
        return
    _kick_fanqie_for_aggregate(aggregate_book_id)


def _aggregate_to_fanqie_chapter(chapter_url: str) -> str | None:
    """Map a virtual/aggregate chapter_url back to its source fanqie chapter_id.

    The aggregate chapter payload carries ``sourceChapterId`` (==
    ``encode_chapter_id("fanqie_local", <fanqie chapter url>)``). When the
    primary source is fanqie_local, delegating to that id lets the reader edge-
    serve straight from the downloader's OS files (downloaded_chapters.jsonl /
    segment_comments) without waiting for the shared-library pipeline — exactly
    the "边下载边返回" contract. Returns None for non-fanqie chapters.
    """
    try:
        payload = unpack_aggregate_chapter_url(chapter_url)
        source_chapter_id = str(payload.get("sourceChapterId") or "")
        if not source_chapter_id:
            return None
        source_id, _ = decode_chapter_id(source_chapter_id)
    except Exception:
        return None
    return source_chapter_id if source_id == "fanqie_local" else None


def _aggregate_to_fanqie_book(book_url: str) -> tuple[str, str] | None:
    """Map a virtual/aggregate book_url back to its source fanqie book.

    Both transient aggregate URLs (which embed ``sources``) and stable published
    library URLs are accepted.  Published URLs only carry the aggregate id, so
    their primary source must be resolved from the library row.  This distinction
    is important for incremental reading: once a book becomes visible, opening it
    must still start/inspect the downloader instead of being trapped behind the
    already-published shared subset.
    """
    try:
        payload = unpack_aggregate_book_url(book_url)
    except Exception:
        return None
    aggregate_book_id = (
        str(payload.get("aggregateBookId") or payload.get("candidateId") or "")
    )
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    for s in sources:
        if not isinstance(s, dict) or str(s.get("sourceId") or "") != "fanqie_local":
            continue
        raw = str(s.get("bookUrl") or "")
        if raw:
            try:
                return encode_book_id("fanqie_local", raw), aggregate_book_id
            except Exception:
                return None
        bid = str(s.get("bookId") or "")
        if bid:
            return bid, aggregate_book_id

    # Stable ``legadohub://aggregate/library/<id>`` URLs intentionally contain
    # no source list. Resolve their current primary source from the book record.
    if aggregate_book_id:
        try:
            book = library_books_service.get_book(aggregate_book_id)
        except Exception:
            book = None
        if book and str(book.get("primarySourceId") or "") == "fanqie_local":
            raw = str(book.get("primaryBookUrl") or "")
            if raw:
                try:
                    return encode_book_id("fanqie_local", raw), aggregate_book_id
                except Exception:
                    return None
    return None


def _merge_incremental_fanqie_toc(shared: dict, edge: dict) -> dict:
    """Merge downloader chapters into a published shared TOC.

    Shared/processed chapters remain authoritative.  Downloader entries only
    fill indexes that the processing pipeline has not published yet, allowing a
    visible partial book to continue growing while it is being downloaded.
    """
    by_index: dict[int, dict] = {}
    for item in edge.get("chapters", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", 0) or 0)
        except (TypeError, ValueError):
            continue
        if index > 0:
            by_index[index] = item
    for item in shared.get("chapters", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", 0) or 0)
        except (TypeError, ValueError):
            continue
        if index > 0:
            by_index[index] = item
    return {
        **shared,
        "chapters": [by_index[index] for index in sorted(by_index)],
        "debug": {
            **(shared.get("debug") if isinstance(shared.get("debug"), dict) else {}),
            "edgeFanqie": True,
            "incremental": True,
        },
    }


def _fanqie_toc_to_shared(
    fanqie_toc: dict,
    *,
    aggregate_book_id: str,
    book_id: str,
) -> dict:
    """Rebuild a fanqie plugin toc into the virtual aggregate toc shape.

    Each fanqie chapter URL is mapped back to a ``legadohub_ai_aggregate``
    chapter id (embedding the fanqie ``sourceChapterId``), so the Reading client
    keeps navigating inside the aggregate subscription while every chapter read
    edge-serves straight from the downloader's incremental files.
    """
    chapters: list[dict] = []
    for position, raw in enumerate(fanqie_toc.get("chapters", []) or [], start=1):
        if not isinstance(raw, dict):
            continue
        raw_chapter_url = str(raw.get("rawChapterUrl") or raw.get("chapterUrl") or "")
        title = str(raw.get("title") or "")
        try:
            index = int(raw.get("index", position) or position)
        except (TypeError, ValueError):
            index = position
        if not raw_chapter_url:
            continue
        source_chapter_id = encode_chapter_id("fanqie_local", raw_chapter_url)
        read_chapter_id = encode_chapter_id(
            VIRTUAL_SOURCE_ID,
            make_aggregate_chapter_url(
                aggregate_book_id=aggregate_book_id,
                source_chapter_id=source_chapter_id,
                title=title,
                index=index,
            ),
        )
        chapters.append(
            {
                "sourceId": VIRTUAL_SOURCE_ID,
                "chapterId": read_chapter_id,
                "index": index,
                "title": title,
                "updateTime": "",
            }
        )
    return {
        "implemented": True,
        "bookId": book_id,
        "chapters": chapters,
        "debug": {"aggregate": True, "edgeFanqie": True, "published": False},
    }


def _pending_chapter_response(
    result: dict,
    *,
    chapter_id: str,
    message: str,
) -> dict:
    """HTTP-200 placeholder for a not-yet-downloaded fanqie chapter (edge read).

    Returns 200 with empty content + ``debug.retryable`` so the Reading client
    keeps re-requesting while the download streams in; mirrors the fanqie_local
    plugin's own ``_pending_chapter`` contract.
    """
    base = _public_chapter_response(result, chapter_id=chapter_id)
    base["content"] = ""
    base["debug"] = {
        "retryable": True,
        **(result.get("debug") if isinstance(result.get("debug"), dict) else {}),
        "msg": message,
    }
    return base


def _require_third_party_plugin(
    catalog: Catalog,
    source_id: str,
    capability: str,
    *,
    label: str,
    target_url: str,
) -> None:
    plugin = catalog.scheduler._plugins.get(source_id)
    if (
        not plugin
        or not plugin.metadata.enabled
        or plugin.metadata.is_official_source()
        or capability not in plugin.capabilities
    ):
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    parsed = urlparse(target_url)
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    allowed_hosts = {
        str(domain or "").lower().lstrip(".").rstrip(".")
        for domain in plugin.metadata.domains
        if str(domain or "").strip()
    }
    for base_url in plugin.metadata.base_urls:
        base_hostname = str(urlparse(str(base_url or "")).hostname or "").lower().rstrip(".")
        if base_hostname:
            allowed_hosts.add(base_hostname)
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or not any(hostname == allowed or hostname.endswith(f".{allowed}") for allowed in allowed_hosts)
    ):
        raise HTTPException(status_code=404, detail=f"{label}不存在")


def _require_review_plugin(
    catalog: Catalog,
    source_id: str,
    capability: str,
    *,
    label: str,
    target_url: str,
) -> None:
    plugin = catalog.scheduler._plugins.get(source_id)
    if (
        not plugin
        or not plugin.metadata.enabled
        or capability not in plugin.capabilities
    ):
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    parsed = urlparse(target_url)
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    allowed_hosts = {
        str(domain or "").lower().lstrip(".").rstrip(".")
        for domain in plugin.metadata.domains
        if str(domain or "").strip()
    }
    for base_url in plugin.metadata.base_urls:
        base_hostname = str(urlparse(str(base_url or "")).hostname or "").lower().rstrip(".")
        if base_hostname:
            allowed_hosts.add(base_hostname)
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or not any(hostname == allowed or hostname.endswith(f".{allowed}") for allowed in allowed_hosts)
    ):
        raise HTTPException(status_code=404, detail=f"{label}不存在")


def _public_text(value: Any, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _public_book_response(
    data: dict,
    *,
    source_id: str,
    book_id: str,
    base_api: str,
) -> dict:
    return {
        "implemented": True,
        "data": {
            "sourceId": source_id,
            "bookId": book_id,
            "name": _public_text(data.get("name"), max_length=500),
            "author": _public_text(data.get("author"), max_length=300),
            "coverUrl": _public_text(data.get("coverUrl"), max_length=4096),
            "intro": _public_text(data.get("intro"), max_length=12000),
            "kind": _public_text(data.get("kind"), max_length=500),
            "lastChapter": _public_text(data.get("lastChapter"), max_length=500),
            "wordCount": data.get("wordCount", ""),
            "status": _public_text(data.get("status"), max_length=100),
            "updateTime": format_reading_update_time(data.get("updateTime", "")),
            "bookUrl": f"{base_api}/api/legado/book/{book_id}",
            "tocUrl": f"{base_api}/api/legado/book/{book_id}/toc",
        },
    }


def _public_toc_response(
    result: dict,
    *,
    source_id: str,
    book_id: str,
    base_api: str,
) -> dict:
    chapters = []
    for position, raw in enumerate(result.get("chapters", []) or [], start=1):
        if not isinstance(raw, dict):
            continue
        chapter_id = _public_text(raw.get("chapterId"), max_length=_MAX_EXTERNAL_ID_LENGTH)
        if source_id != VIRTUAL_SOURCE_ID:
            raw_chapter_url = _public_text(
                raw.get("rawChapterUrl") or raw.get("chapterUrl"),
                max_length=16_384,
            )
            if raw_chapter_url:
                chapter_id = encode_chapter_id(source_id, raw_chapter_url)
        try:
            encoded_source_id, _ = decode_chapter_id(chapter_id)
        except Exception:
            continue
        if encoded_source_id != source_id or len(chapter_id) > _MAX_EXTERNAL_ID_LENGTH:
            continue
        try:
            chapter_index = int(raw.get("index", position) or position)
        except (TypeError, ValueError):
            chapter_index = position
        preview_only = bool(raw.get("previewOnly", False))
        is_vip = bool(raw.get("isVip", False))
        is_paid = bool(raw.get("isPaid", is_vip))
        chapters.append(
            {
                "sourceId": source_id,
                "chapterId": chapter_id,
                "index": chapter_index,
                "title": _public_text(raw.get("title"), max_length=1000),
                "chapterUrl": f"{base_api}/api/legado/chapter/{chapter_id}",
                "updateTime": format_reading_update_time(raw.get("updateTime", "")),
                "isVip": is_vip,
                "isPaid": is_paid,
                "isPay": bool(raw.get("isPay", is_vip and not preview_only)),
                "previewOnly": preview_only,
            }
        )
    return {
        "implemented": True,
        "bookId": book_id,
        "chapters": chapters,
    }


def _public_chapter_response(result: dict, *, chapter_id: str) -> dict:
    extra = result.get("extra") if isinstance(result.get("extra"), dict) else {}
    preview_only = bool(result.get("previewOnly", extra.get("previewOnly", False)))
    is_vip = bool(result.get("isVip", extra.get("isVip", result.get("isPaid", False))))
    safe_extra = {
        key: extra[key]
        for key in ("previewOnly", "isVip", "contentAccess")
        if key in extra and isinstance(extra[key], (str, int, float, bool, type(None)))
    }
    return {
        "implemented": True,
        "chapterId": chapter_id,
        "title": _public_text(result.get("title"), max_length=1000),
        "content": str(result.get("content", "") or ""),
        "authRequired": bool(result.get("authRequired", False)),
        "isVip": is_vip,
        "isPaid": bool(result.get("isPaid", is_vip)),
        "isPay": bool(result.get("isPay", is_vip and not preview_only)),
        "previewOnly": preview_only,
        "extra": safe_extra,
    }


async def _chapter_reviews(chapter_id: str, *, catalog: Catalog | None = None) -> dict:
    cached = chapter_review_cache.get(chapter_id)
    if cached is not None:
        return cached
    reviews = await (catalog or Catalog()).chapter_reviews(chapter_id)
    chapter_review_cache.set(chapter_id, reviews)
    return reviews


def _purify_chapter_content_for_reading(
    content: str,
    *,
    source_id: str | None = None,
) -> str:
    """Read-path ad/watermark gate (same pure rules as write-time purify).

    Covers already-stored library chapters and third-party direct reads without
    waiting for reprocessing. Safe/no-op when patterns do not match.
    """
    from app.services.content_purify import purify_for_reading

    return purify_for_reading(content, source_id=source_id)


async def _strip_author_say_from_chapter_content(
    *,
    chapter_id: str,
    content: str,
    catalog: Catalog | None = None,
) -> str:
    """Fetch chapter reviews and strip embedded 作家说 from the body when present.

    Reading path always tries the reviews API (cached via chapter_review_cache).
    Subscription processing still does durable strip at write time; this covers
    already-stored chapters and third-party bodies that still carry author notes.
    """
    from app.services.author_say_strip import (
        extract_author_say_texts,
        strip_overlapping_author_say,
    )

    if not content or not content.strip():
        return content
    try:
        reviews = await _chapter_reviews(chapter_id, catalog=catalog)
    except Exception:
        logger.debug(
            "author-say strip skipped; reviews unavailable for %s",
            chapter_id,
            exc_info=True,
        )
        return content
    if not isinstance(reviews, dict):
        return content
    author_texts = extract_author_say_texts(reviews)
    if not author_texts:
        return content
    return strip_overlapping_author_say(content, author_texts)


async def _apply_reading_content_gates(
    *,
    chapter_id: str,
    content: str,
    source_id: str | None = None,
    catalog: Catalog | None = None,
    apply_purify: bool = True,
    strip_author_say: bool = True,
) -> str:
    """Reading delivery gates: optional ad purify, then 作家说 strip.

    Direct source reads use purify → author-say. Already-selected aggregate
    chapters skip phrase-based purify and only apply the author-say boundary.
    Shared chapters were already cleaned during aggregation; their body path
    must not re-enter the live review/source bridge.
    """
    cleaned = (
        _purify_chapter_content_for_reading(content, source_id=source_id)
        if apply_purify
        else content
    )
    if not strip_author_say:
        return cleaned
    return await _strip_author_say_from_chapter_content(
        chapter_id=chapter_id,
        content=cleaned,
        catalog=catalog,
    )


_LOCAL_MEDIA_EXT_RE = r"[0-9a-fA-F]{40}\.(?:jpeg|jpg|png|gif|webp|avif|heic|heif)"


@router.get("/media/{book_id}/{filename}")
async def legado_local_comment_media(book_id: str, filename: str):
    """Serve a fanqie_local comment/avatar image straight from fqdown's local
    images/ cache (save_dir/<book_id>/images/<sha1>.<ext>), resolved only by
    fqdown's sha1(url) mapping. Read-only: the downloader is never written to
    and nothing is piped through the img-upload queue. Malformed or not-yet
    cached -> 404 so the <img onerror> hides gracefully.
    """
    if not book_id.isdigit():
        raise HTTPException(status_code=404, detail="bad_book")
    if not re.fullmatch(_LOCAL_MEDIA_EXT_RE, filename or ""):
        raise HTTPException(status_code=404, detail="bad_media")
    save_dir = await get_save_dir()
    images_root = Path(save_dir) / book_id / "images"
    # 兼容两种落盘：images/<file> 平铺，或 images/<子目录>/<file>（如 comments/）。
    # 只枚举第一层子目录，绝不递归；找不到才 404，<img onerror> 静默隐藏。
    targets = [images_root / filename]
    try:
        targets += [
            child / filename for child in images_root.iterdir()
            if child.is_dir() and (child / filename).is_file()
        ]
    except OSError:
        pass
    target = next((t for t in targets if t.is_file()), None)
    if target is None:
        raise HTTPException(status_code=404, detail="not_cached")
    # 文件名是 sha1(url) 内容寻址，一个 URL 永远对应同一个字节流 → 不可变。
    # 用长 max-age + immutable + CDN s-maxage，让浏览器与 Cloudflare 边缘按
    # URL 末尾的静态扩展名（.png/.jpeg/.gif/.webp/...）持久缓存，避免反复回源。
    return FileResponse(
        target,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable, s-maxage=31536000",
            "CDN-Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{filename}"',
        },
    )


@router.get("/book/{book_id}")
async def get_book(request: Request, book_id: str) -> dict:
    user = auth_service.require_reading_user(request, touch=False)
    # ``lane`` is an optional dual-source disambiguator from search bookUrl; ignored.
    _reject_query_anomalies(request, {"lane"})
    book_id = _validated_external_id(book_id, label="书籍")
    source_id, book_url = _decode_book_identity(book_id)
    if source_id == "fanqie_local":
        # 点开阅读 -> 触发下载器整本下载（fire-and-forget，永不阻塞/必不 raise）。
        spawn_fanqie_trigger_for_url(book_url)
    with reading_access_limiter.guard(user.user_id, "metadata"):
        base_api = get_public_base_url(request)
        if source_id == VIRTUAL_SOURCE_ID:
            resolved = _aggregate_to_fanqie_book(book_url)
            if resolved:
                # A book may already be published with only its first few shared
                # chapters. Opening it must still start the whole-book download.
                fanqie_book_id, aggregate_book_id = resolved
                _kick_fanqie_for_aggregate_and(aggregate_book_id, fanqie_book_id)
            shared = library_books_service.legado_book_detail(book_id, base_api=base_api)
            if shared is None:
                # 未发布就点开详情：直接委托 fanqie 插件的本地落盘回填书名/作者/简介/封面，
                # 绝不因共享库未落盘就 404。
                catalog = Catalog(base_api=base_api)
                if resolved:
                    fanqie_book_id, _aggregate_book_id = resolved
                    edge = await catalog.book_detail(fanqie_book_id)
                    edge_data = edge.get("data") if isinstance(edge, dict) else None
                    if isinstance(edge_data, dict):
                        return _public_book_response(
                            edge_data,
                            source_id=source_id,
                            book_id=book_id,
                            base_api=base_api,
                        )
                raise HTTPException(status_code=404, detail="书籍尚未发布")
            return _public_book_response(
                dict(shared.get("data") or {}),
                source_id=source_id,
                book_id=book_id,
                base_api=base_api,
            )
        catalog = Catalog(base_api=base_api)
        _require_third_party_plugin(
            catalog,
            source_id,
            "detail",
            label="书籍",
            target_url=book_url,
        )
        result = await catalog.book_detail(book_id)
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            if source_id == "fanqie_local":
                # 下载器预览超时/还没产出：触发已在上方发出，只回可刷新占位，
                # 绝不 404（否则客户端放弃这本书）。后续刷新读到本地增量即补全。
                data = {
                    "name": "",
                    "author": "",
                    "coverUrl": "",
                    "intro": "书籍下载/解析中，请稍后刷新。",
                    "kind": "",
                    "lastChapter": "",
                    "wordCount": "",
                    "status": "下载中",
                }
            else:
                raise HTTPException(status_code=404, detail="书籍读取失败")
        return _public_book_response(
            data,
            source_id=source_id,
            book_id=book_id,
            base_api=base_api,
        )


@router.get("/book/{book_id}/toc")
async def get_toc(request: Request, book_id: str) -> dict:
    user = auth_service.require_reading_user(request, touch=False)
    _reject_query_anomalies(request, {"lane"})
    book_id = _validated_external_id(book_id, label="书籍")
    source_id, book_url = _decode_book_identity(book_id)
    with reading_access_limiter.guard(user.user_id, "metadata"):
        base_api = get_public_base_url(request)
        if source_id == VIRTUAL_SOURCE_ID:
            catalog = Catalog(base_api=base_api)
            resolved = _aggregate_to_fanqie_book(book_url)
            edge_shared: dict | None = None
            if resolved:
                fanqie_book_id, aggregate_book_id = resolved
                _kick_fanqie_for_aggregate_and(aggregate_book_id, fanqie_book_id)
                # Always inspect the incremental journal, even after the shared
                # book is visible. Previously this path only ran when ``shared``
                # was None, freezing clients at the published subset.
                edge = await catalog.toc(fanqie_book_id)
                if edge.get("chapters"):
                    edge_shared = _fanqie_toc_to_shared(
                        edge,
                        aggregate_book_id=aggregate_book_id,
                        book_id=book_id,
                    )
            shared = library_books_service.legado_toc(book_id, base_api=base_api)
            if shared is None:
                if edge_shared is not None:
                    return _public_toc_response(
                        edge_shared,
                        source_id=source_id,
                        book_id=book_id,
                        base_api=base_api,
                    )
                raise HTTPException(status_code=404, detail="书籍尚未发布")
            if edge_shared is not None:
                shared = _merge_incremental_fanqie_toc(shared, edge_shared)
            return _public_toc_response(
                shared,
                source_id=source_id,
                book_id=book_id,
                base_api=base_api,
            )
        catalog = Catalog(base_api=base_api)
        _require_third_party_plugin(
            catalog,
            source_id,
            "toc",
            label="书籍",
            target_url=book_url,
        )
        result = await catalog.toc(book_id)
        return _public_toc_response(
            result,
            source_id=source_id,
            book_id=book_id,
            base_api=base_api,
        )


@router.get("/chapter/{chapter_id}")
async def get_chapter(request: Request, chapter_id: str) -> dict:
    user = auth_service.require_reading_user(request, touch=False)
    _reject_query_anomalies(request, {"lane"})
    chapter_id = _validated_external_id(chapter_id, label="章节")
    source_id, chapter_url = _decode_chapter_identity(chapter_id)
    with reading_access_limiter.guard(user.user_id, "chapter"):
        catalog = Catalog(base_api=get_public_base_url(request))
        if source_id == VIRTUAL_SOURCE_ID:
            # Chapter reads are another independent entrypoint (cached detail/TOC
            # can bypass those routes), so keep the downloader alive here too.
            _kick_fanqie_on_missing_chapter(chapter_id, chapter_url)
            shared = library_books_service.legado_chapter(chapter_id)
            if shared is None:
                # fanqie_local-primary 聚合章：直接委托 fanqie 插件的边下边读
                # （读 downloaded_chapters.jsonl / segment_comments，命中即返回，
                # 未命中触发整本下载并回 retryable 占位，客户端刷新即补）。
                fanqie_chapter_id = _aggregate_to_fanqie_chapter(chapter_url)
                if fanqie_chapter_id:
                    edge = await catalog.chapter(fanqie_chapter_id)
                    if str(edge.get("content") or "").strip():
                        return _public_chapter_response(edge, chapter_id=chapter_id)
                    _kick_fanqie_on_missing_chapter(chapter_id, chapter_url)
                    return _pending_chapter_response(
                        edge,
                        chapter_id=chapter_id,
                        message="章节下载中，请稍后重试。",
                    )
                _kick_fanqie_on_missing_chapter(chapter_id, chapter_url)
                raise HTTPException(status_code=404, detail="章节尚未发布")
            content = await _apply_reading_content_gates(
                chapter_id=chapter_id,
                content=str(shared.get("content", "") or ""),
                source_id=source_id,
                catalog=catalog,
                apply_purify=False,
                strip_author_say=False,
            )
            shared = {**shared, "content": content}
            return _public_chapter_response(shared, chapter_id=chapter_id)
        _require_third_party_plugin(
            catalog,
            source_id,
            "chapter",
            label="章节",
            target_url=chapter_url,
        )
        result = await catalog.chapter(chapter_id)
        content = await _apply_reading_content_gates(
            chapter_id=chapter_id,
            content=str(result.get("content", "") or ""),
            source_id=source_id,
            catalog=catalog,
        )
        result = {**result, "content": content}
        return _public_chapter_response(result, chapter_id=chapter_id)


@router.get("/chapter/{chapter_id}/reviews")
async def get_chapter_reviews(request: Request, chapter_id: str) -> dict:
    user = auth_service.require_reading_user(request, touch=False)
    _reject_query_anomalies(request, {"lane"})
    chapter_id = _validated_external_id(chapter_id, label="章节")
    source_id, chapter_url = _decode_chapter_identity(chapter_id)
    with reading_access_limiter.guard(user.user_id, "reviews"):
        catalog = Catalog(base_api=get_public_base_url(request))
        if source_id == VIRTUAL_SOURCE_ID:
            if library_books_service.legado_chapter(chapter_id) is None:
                # fanqie_local 主源聚合章：先确保整本下载在跑，再委托插件的
                # 边下边读直接返回 segment_comments/<id>.json（下到哪返回到哪）。
                fanqie_chapter_id = _aggregate_to_fanqie_chapter(chapter_url)
                if fanqie_chapter_id:
                    _kick_fanqie_on_missing_chapter(chapter_id, chapter_url)
                    return await catalog.chapter_reviews(fanqie_chapter_id)
                raise HTTPException(status_code=404, detail="章节尚未发布")
        else:
            _require_review_plugin(
                catalog,
                source_id,
                "chapter_reviews",
                label="章节",
                target_url=chapter_url,
            )
        return await _chapter_reviews(chapter_id, catalog=catalog)


@router.get("/chapter/{chapter_id}/reviews/view", response_class=HTMLResponse)
async def get_chapter_review_view(
    request: Request,
    chapter_id: str,
    tab: str = "chapter",
    paragraphId: str | None = None,
    paragraphIds: str | None = None,
    rootReviewId: str | None = None,
    page: str = "1",
    pageSize: str = "10",
    cursorId: str = "0",
) -> HTMLResponse:
    user = auth_service.require_reading_user(request, touch=False)
    _reject_query_anomalies(
        request,
        {
            "tab",
            "paragraphId",
            "paragraphIds",
            "rootReviewId",
            "page",
            "pageSize",
            "cursorId",
            "lane",
        },
    )
    chapter_id = _validated_external_id(chapter_id, label="章节")
    source_id, chapter_url = _decode_chapter_identity(chapter_id)
    if tab not in {"chapter", "paragraph"}:
        raise HTTPException(status_code=422, detail="tab 无效")
    parsed_paragraph_id = _query_int(
        paragraphId, field="paragraphId", minimum=-1, maximum=_MAX_NUMERIC_ID
    )
    parsed_root_review_id = _query_int(
        rootReviewId, field="rootReviewId", minimum=1, maximum=_MAX_NUMERIC_ID
    )
    parsed_page = _query_int(page, field="page", minimum=1, maximum=1000, default=1) or 1
    page_size = _query_int(pageSize, field="pageSize", minimum=1, maximum=50, default=10) or 10
    cursor_id = _query_int(cursorId, field="cursorId", minimum=0, maximum=_MAX_NUMERIC_ID, default=0) or 0
    if paragraphIds is not None and (len(paragraphIds) > 1024 or any(ord(char) < 32 for char in paragraphIds)):
        raise HTTPException(status_code=422, detail="paragraphIds 无效")

    with reading_access_limiter.guard(user.user_id, "reviews"):
        catalog = Catalog(base_api=get_public_base_url(request))
        # 评论钻取目标：虚拟 fanqie 章尚未发布时，转回直连 fanqie 源，
        # 由插件从下载器本地落盘边下边读（封面/章节/段评），不再 404。
        data_chapter_id = chapter_id
        data_chapter_url = chapter_url
        data_source_id = source_id
        if source_id == VIRTUAL_SOURCE_ID:
            chapter = library_books_service.legado_chapter(chapter_id)
            if chapter is None:
                fanqie_chapter_id = _aggregate_to_fanqie_chapter(chapter_url)
                if not fanqie_chapter_id:
                    raise HTTPException(status_code=404, detail="章节尚未发布")
                _kick_fanqie_on_missing_chapter(chapter_id, chapter_url)
                data_chapter_id = fanqie_chapter_id
                _s, data_chapter_url = decode_chapter_id(fanqie_chapter_id)
                data_source_id = "fanqie_local"
        else:
            _require_third_party_plugin(
                catalog,
                source_id,
                "chapter",
                label="章节",
                target_url=chapter_url,
            )
            _require_review_plugin(
                catalog,
                source_id,
                "chapter_reviews",
                label="章节",
                target_url=chapter_url,
            )
            chapter = await catalog.chapter(chapter_id)
        reviews = await _chapter_reviews(data_chapter_id, catalog=catalog)
        chapter_title = str(chapter.get("title") or "本章评论") if chapter else "本章评论"
        paragraph_detail = None
        page_hot_detail = None
        chapter_detail = None
        reply_detail = None
        if parsed_root_review_id is not None:
            reply_detail = await catalog.review_replies(
                data_chapter_id,
                parsed_root_review_id,
                page=parsed_page,
                page_size=page_size,
                cursor_id=cursor_id,
            )
            reply_detail = await _enrich_review_media(
                catalog, reply_detail, data_source_id, data_chapter_url
            )
            tab = "paragraph"
        elif paragraphIds:
            try:
                parsed_ids = list(dict.fromkeys(
                    int(value.strip())
                    for value in paragraphIds.split(",")
                    if value.strip()
                ))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="paragraphIds 必须是逗号分隔的非负整数") from exc
            if (
                not parsed_ids
                or len(parsed_ids) > 50
                or any(value < 0 or value > _MAX_NUMERIC_ID for value in parsed_ids)
            ):
                raise HTTPException(status_code=422, detail="paragraphIds 数量或取值无效")
            page_hot_detail = await catalog.page_hot_reviews(
                data_chapter_id,
                parsed_ids,
                page=parsed_page,
                page_size=page_size,
            )
            page_hot_detail = await _enrich_review_media(
                catalog, page_hot_detail, data_source_id, data_chapter_url
            )
            tab = "paragraph"
        elif parsed_paragraph_id is not None:
            paragraph_detail = await catalog.paragraph_reviews(
                data_chapter_id,
                parsed_paragraph_id,
                page=parsed_page,
                page_size=page_size,
            )
            paragraph_detail = await _enrich_review_media(
                catalog, paragraph_detail, data_source_id, data_chapter_url
            )
            tab = "paragraph"
        elif tab == "chapter" and parsed_page > 1:
            chapter_detail = await catalog.chapter_say(
                data_chapter_id,
                page=parsed_page,
                page_size=page_size,
            )
            chapter_detail = await _enrich_review_media(
                catalog, chapter_detail, data_source_id, data_chapter_url
            )
        base_api = get_public_base_url(request)
        review_view_url = f"{base_api}/api/legado/chapter/{chapter_id}/reviews/view"
        return HTMLResponse(
            render_chapter_reviews_html(
                chapter_title=chapter_title,
                reviews=reviews,
                review_view_url=review_view_url,
                active_tab=tab,
                selected_paragraph_id=parsed_paragraph_id,
                paragraph_detail=paragraph_detail,
                page_hot_detail=page_hot_detail,
                chapter_detail=chapter_detail,
                reply_detail=reply_detail,
            ),
            headers={
                "X-Frame-Options": "SAMEORIGIN",
                "Content-Security-Policy": "frame-ancestors 'self'; base-uri 'self'; object-src 'none'",
            },
        )
