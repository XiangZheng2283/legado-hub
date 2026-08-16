"""Catalog orchestration for direct and aggregate chapter reviews."""

from __future__ import annotations

import html
from typing import Any
from pathlib import Path

from app.services.aggregate_reviews import (
    align_hot_paragraph_reviews,
    empty_aggregate_reviews,
    normalize_hot_paragraph_reviews,
    summarize_reviews,
)
from app.services.aggregate_virtual_source import VIRTUAL_SOURCE_ID, unpack_aggregate_chapter_url
from app.services.library_books import library_books_service
from app.services.media_upload_queue import media_upload_queue_service
from app.source_plugins.id_codec import decode_chapter_id, encode_chapter_id

QIDIAN_APP_SOURCE_ID = "qidian_com_app"
QIDIAN_WEB_SOURCE_ID = "qidian_com_web"
QIDIAN_SOURCE_IDS = {QIDIAN_APP_SOURCE_ID, QIDIAN_WEB_SOURCE_ID}

_LOCAL_MEDIA_PREFIX = "/api/legado/media/"


def _comment_src_attr(url: str) -> str:
    """Attribute-safe media URL for contentHtml/src.

    只转义引号、保留 & 原样：Legado 客户端把 content/contentHtml 当字面文本读取
    src，若把 '&' 转成 '&amp;' 会使签名查询串失效（403/无法加载）。
    """
    return str(url or "").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_comment_url(value: Any) -> str:
    """只放行 http/https 的原始 CDN URL（头像/评论图客户端直载），其余（空白/危险协议）返空串。"""
    u = str(value or "").strip()
    low = u.lower()
    if low.startswith("http://"):
        return "https://" + u[len("http://"):]  # 升级避免 https 页 mixed-content 拦截
    return u if low.startswith("https://") else ""


def _fanqie_ref_to_media_url(ref: str) -> str:
    """Local fqdown media ref {save_dir}/<book_id>/images/<sha1>.<ext> -> hub route.

    Returns "" for anything that is not the fanqie_local images/ shape so the
    caller falls back to the legacy upload-queue mapping for other sources.
    """
    path = Path(str(ref).strip())
    filename = path.name
    # 仅识别 fqdown 本地盘绝对路径 save_dir/<book_id>/images/<sha1>.<ext>，
    # 兼容 images/ 平铺与 images/<子目录>/（如 images/comments）两种落盘：
    # 只要路径里有一段 "images"，其父段是数字 book_id 即命中，用 filename 拼路由。
    # 相对 EPUB 包内路径（如 OEBPS/images/...）不在此列，交给上传队列表决。
    if not path.is_absolute() or not filename:
        return ""
    parts = path.parts
    if "images" not in parts:
        return ""
    idx = parts.index("images")
    if idx + 1 >= len(parts):
        return ""
    book_id = parts[idx - 1] if idx >= 1 else ""
    if not book_id.isdigit():
        return ""
    return f"{_LOCAL_MEDIA_PREFIX}{book_id}/{filename}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _direct_review_response(chapter_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "implemented": True,
        "chapterId": chapter_id,
        "paragraphs": result.get("paragraphs", {}),
        "hotParagraphReviews": result.get("hotParagraphReviews", []),
        "chapterEnd": result.get("chapterEnd", []),
        "chapterEndHot": result.get("chapterEndHot", []),
        "authorReviews": result.get("authorReviews", []),
        "summary": result.get("summary", {}),
        "debug": result.get("debug", {}),
    }


async def _direct_chapter_reviews(scheduler: Any, chapter_id: str) -> dict[str, Any]:
    try:
        source_id, chapter_url = decode_chapter_id(chapter_id)
    except Exception:
        return {
            "implemented": True,
            "chapterId": chapter_id,
            "paragraphs": {},
            "hotParagraphReviews": [],
            "chapterEnd": [],
            "chapterEndHot": [],
            "authorReviews": [],
            "summary": {},
            "debug": {"error": "invalid chapter_id format"},
        }
    result = await scheduler.chapter_reviews(source_id, chapter_url)
    return _direct_review_response(chapter_id, result)


async def _review_operation(
    scheduler: Any,
    operation: str,
    source_id: str,
    chapter_url: str,
    *args: Any,
    **kwargs: Any,
) -> tuple[dict[str, Any], str, str]:
    """Run one review operation with host-owned Qidian App-first fallback."""
    candidates = (
        [QIDIAN_APP_SOURCE_ID, QIDIAN_WEB_SOURCE_ID]
        if source_id in QIDIAN_SOURCE_IDS
        else [source_id]
    )
    last_result: dict[str, Any] = {}
    for index, candidate in enumerate(candidates):
        method = getattr(scheduler, operation)
        result = await method(candidate, chapter_url, *args, **kwargs)
        if not isinstance(result, dict):
            result = {}
        last_result = result
        debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
        if not debug.get("error"):
            if candidate == QIDIAN_APP_SOURCE_ID and source_id == QIDIAN_WEB_SOURCE_ID:
                reason = "qidian_app_preferred"
            elif candidate == QIDIAN_WEB_SOURCE_ID and index > 0:
                reason = "app_failed_web_fallback"
            else:
                reason = "primary_source"
            return result, candidate, reason
    return last_result, candidates[-1], "app_failed_web_fallback" if len(candidates) > 1 else "primary_source"


def _review_items(value: Any, seen: set[int], result: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)
        if "avatarRef" in value or "imageRefs" in value:
            result.append(value)
        for nested in value.values():
            _review_items(nested, seen, result)
    elif isinstance(value, list):
        for nested in value:
            _review_items(nested, seen, result)


async def _enrich_review_media(
    scheduler: Any,
    payload: dict[str, Any],
    source_id: str,
    chapter_url: str,
) -> dict[str, Any]:
    """Replace private Fanqie refs with completed queue URLs only."""
    reviews: list[dict[str, Any]] = []
    _review_items(payload, set(), reviews)
    refs = {
        str(ref).strip()
        for review in reviews
        for ref in ([review.get("avatarRef")] if review.get("avatarRef") else [])
        + (review.get("imageRefs") if isinstance(review.get("imageRefs"), list) else [])
        if str(ref).strip()
    }
    resolved: dict[str, str] = {}
    local_media = False
    for ref in refs:
        local_url = _fanqie_ref_to_media_url(ref)
        if local_url:
            resolved[ref] = local_url
            local_media = True
        else:
            resolved[ref] = media_upload_queue_service.find_uploaded(ref=ref)
    media_uploaded = sum(1 for url in resolved.values() if url)
    for review in reviews:
        avatar_ref = str(review.pop("avatarRef", "") or "").strip()
        image_refs = review.pop("imageRefs", [])
        if not isinstance(image_refs, list):
            image_refs = []
        avatar_local = resolved.get(avatar_ref, "")
        # 原始 CDN URL（客户端直载优先）；无 → 本地本地盘兜底。
        avatar_orig = _safe_comment_url(review.pop("avatarUrl", ""))
        avatar_url = avatar_orig or avatar_local
        if avatar_url:
            review["avatar"] = avatar_url
        # 源端已保序（每个原图一个槽位）：原 URL 优先、本地兜底，绝不丢位/去重。
        image_urls_local = [resolved.get(str(ref).strip(), "") for ref in image_refs]
        image_orig = [_safe_comment_url(u) for u in (review.pop("imageSrcs", []) or [])]
        image_urls = [
            (image_orig[i] if i < len(image_orig) and image_orig[i] else image_urls_local[i])
            for i in range(len(image_urls_local))
        ]
        if any(image_urls):
            review["imageUrls"] = image_urls
            review["imageUrl"] = next((u for u in image_urls if u), "")
        # 只提供结构化字段（avatar / imageUrls / imageUrl），正文保持纯文本 content。
        # 版式统一交给 _review_card：头像框 + 用户名 + 正文 + 独立媒体框，
        # 不再拼自包含 contentHtml（内嵌 <img> 会脱离媒体框、挤乱换行）。
    debug = payload.setdefault("debug", {})
    if isinstance(debug, dict) and refs:
        debug["mediaFound"] = len(refs)
        debug["mediaUploaded"] = media_uploaded
        debug["mediaFailed"] = len(refs) - media_uploaded
        debug["mediaSource"] = "local_media" if local_media else "media_upload_queue"
    return payload

def _mapped_review_target(chapter_id: str) -> tuple[str, str, str, bool]:
    source_id, chapter_url = decode_chapter_id(chapter_id)
    if source_id != VIRTUAL_SOURCE_ID:
        return source_id, chapter_url, chapter_id, False
    payload = unpack_aggregate_chapter_url(chapter_url)
    mapped_chapter_id = str(payload.get("sourceChapterId") or "")
    if not mapped_chapter_id:
        raise ValueError("source_chapter_missing")
    mapped_source_id, mapped_chapter_url = decode_chapter_id(mapped_chapter_id)
    return mapped_source_id, mapped_chapter_url, mapped_chapter_id, True


async def chapter_reviews(scheduler: Any, chapter_id: str) -> dict[str, Any]:
    """Resolve aggregate mapping, host-owned App-to-Web fallback, and alignment."""
    try:
        source_id, chapter_url = decode_chapter_id(chapter_id)
    except Exception:
        return await _direct_chapter_reviews(scheduler, chapter_id)
    if source_id != VIRTUAL_SOURCE_ID:
        result, actual_source_id, mapping_reason = await _review_operation(
            scheduler,
            "chapter_reviews",
            source_id,
            chapter_url,
        )
        response = _direct_review_response(chapter_id, result)
        response.update({
            "mappedSourceId": actual_source_id,
            "mappingReason": mapping_reason,
        })
        return await _enrich_review_media(scheduler, response, actual_source_id, chapter_url)

    try:
        payload = unpack_aggregate_chapter_url(chapter_url)
        source_chapter_id = str(payload.get("sourceChapterId") or "")
    except Exception as exc:
        return empty_aggregate_reviews(
            chapter_id=chapter_id,
            mapping_reason=f"invalid_aggregate_chapter:{exc}",
        )
    if not source_chapter_id:
        return empty_aggregate_reviews(
            chapter_id=chapter_id,
            mapping_reason="source_chapter_missing",
        )

    shared_chapter = library_books_service.legado_chapter(chapter_id)
    if shared_chapter is None:
        return empty_aggregate_reviews(
            chapter_id=chapter_id,
            mapped_chapter_id=source_chapter_id,
            mapping_reason="chapter_not_published",
        )
    try:
        mapped_source_id, mapped_chapter_url = decode_chapter_id(source_chapter_id)
    except Exception:
        return empty_aggregate_reviews(
            chapter_id=chapter_id,
            mapped_chapter_id=source_chapter_id,
            mapping_reason="invalid_source_chapter",
        )

    result, mapped_source_id, mapping_reason = await _review_operation(
        scheduler,
        "chapter_reviews",
        mapped_source_id,
        mapped_chapter_url,
    )
    source_chapter_id = encode_chapter_id(mapped_source_id, mapped_chapter_url)

    aggregate_book_id = str(payload.get("aggregateBookId") or "")
    chapter_index = _safe_int(payload.get("index"), 0)
    snapshot_source_ids = [mapped_source_id]
    if mapped_source_id in {"qidian_com_app", "qidian_com_web"}:
        snapshot_source_ids.extend(["qidian_com_app", "qidian_com_web"])
    official_content, snapshot_source_id = library_books_service.source_snapshot_content(
        aggregate_book_id,
        chapter_index,
        snapshot_source_ids,
    )
    hot_reviews = align_hot_paragraph_reviews(
        normalize_hot_paragraph_reviews(result),
        official_content=official_content,
        aggregate_content=str(shared_chapter.get("content") or ""),
    )
    response = {
        "implemented": True,
        "chapterId": chapter_id,
        "mappedChapterId": source_chapter_id,
        "mappedSourceId": mapped_source_id,
        "mappingReason": mapping_reason,
        "paragraphs": result.get("paragraphs", {}),
        "hotParagraphReviews": hot_reviews,
        "chapterEndHot": result.get("chapterEndHot", []),
        "chapterEnd": result.get("chapterEnd", []),
        "authorReviews": result.get("authorReviews", []),
        "summary": dict(result.get("summary", {})) if isinstance(result.get("summary"), dict) else {},
        "debug": {
            **(result.get("debug", {}) if isinstance(result.get("debug"), dict) else {}),
            "aggregate": True,
            "reviewSource": mapping_reason,
            "snapshotSourceId": snapshot_source_id,
        },
    }
    response["summary"].update(summarize_reviews(response))
    return await _enrich_review_media(scheduler, response, mapped_source_id, mapped_chapter_url)


async def _paged_review_operation(
    scheduler: Any,
    chapter_id: str,
    operation: str,
    *args: Any,
    page: int = 1,
    page_size: int = 20,
    **kwargs: Any,
) -> dict[str, Any]:
    """Resolve one paged review call through the mapped source and App-first policy."""
    try:
        source_id, chapter_url, _mapped_chapter_id, aggregate = _mapped_review_target(chapter_id)
    except Exception as exc:
        return {
            "implemented": True,
            "chapterId": chapter_id,
            "comments": [],
            "totalCount": 0,
            "hasMore": False,
            "debug": {"error": str(exc)},
        }
    result, actual_source_id, mapping_reason = await _review_operation(
        scheduler,
        operation,
        source_id,
        chapter_url,
        *args,
        page=page,
        page_size=page_size,
        **kwargs,
    )
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    return {
        **result,
        "implemented": True,
        "chapterId": chapter_id,
        "mappedChapterId": encode_chapter_id(actual_source_id, chapter_url),
        "mappedSourceId": actual_source_id,
        "mappingReason": mapping_reason,
        "debug": {**debug, "aggregate": aggregate, "reviewSource": mapping_reason},
    }


async def page_hot_reviews(
    scheduler: Any,
    chapter_id: str,
    paragraph_ids: list[int],
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    return await _paged_review_operation(
        scheduler,
        chapter_id,
        "page_hot_reviews",
        paragraph_ids,
        page=page,
        page_size=page_size,
    )


async def chapter_say(
    scheduler: Any,
    chapter_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    return await _paged_review_operation(
        scheduler,
        chapter_id,
        "chapter_say",
        page=page,
        page_size=page_size,
    )


async def paragraph_reviews(
    scheduler: Any,
    chapter_id: str,
    paragraph_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    result = await _paged_review_operation(
        scheduler,
        chapter_id,
        "paragraph_reviews",
        paragraph_id,
        page=page,
        page_size=page_size,
    )
    result["paragraphId"] = paragraph_id
    return result


async def review_replies(
    scheduler: Any,
    chapter_id: str,
    root_review_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
    cursor_id: int = 0,
) -> dict[str, Any]:
    result = await _paged_review_operation(
        scheduler,
        chapter_id,
        "review_replies",
        root_review_id,
        page=page,
        page_size=page_size,
        cursor_id=cursor_id,
    )
    result["rootReviewId"] = str(root_review_id)
    return result