"""Reading-facing chapter review markup, cache, and HTML view rendering."""

from __future__ import annotations

import copy
import html
import re
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlencode, urlparse

REVIEW_CACHE_TTL_SECONDS = 600
REVIEW_CACHE_MAX_ITEMS = 256
REVIEW_EMOTICON_CDN = "https://qdfepccdn.qidian.com/gtimg/app_emoji_new/newface_{}.png"
REVIEW_IMAGE_HOST_SUFFIXES = (
    "qidian.com",
    "qpic.cn",
    "myqcloud.com",
    "yuewen.com",
)
_INLINE_EMOTICON_RE = re.compile(r"\[fn=(\d+)\]")


class ChapterReviewCache:
    """Small process-local cache that keeps review failures off the body path."""

    def __init__(self) -> None:
        self._items: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    def get(self, chapter_id: str) -> dict[str, Any] | None:
        cached = self._items.get(chapter_id)
        if cached is None:
            return None
        created_at, payload = cached
        if time.monotonic() - created_at >= REVIEW_CACHE_TTL_SECONDS:
            self._items.pop(chapter_id, None)
            return None
        self._items.move_to_end(chapter_id)
        return copy.deepcopy(payload)

    def set(self, chapter_id: str, payload: dict[str, Any]) -> None:
        self._items[chapter_id] = (time.monotonic(), copy.deepcopy(payload))
        self._items.move_to_end(chapter_id)
        while len(self._items) > REVIEW_CACHE_MAX_ITEMS:
            self._items.popitem(last=False)


chapter_review_cache = ChapterReviewCache()


def _review_id(review: dict[str, Any]) -> str:
    return str(review.get("id") or review.get("reviewId") or "")


def _dedupe_reviews(*buckets: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for bucket in buckets:
        if not isinstance(bucket, list):
            continue
        for review in bucket:
            if not isinstance(review, dict):
                continue
            review_id = _review_id(review)
            if review_id and review_id in seen:
                continue
            result.append(review)
            if review_id:
                seen.add(review_id)
    return result


def _count_label(value: Any) -> str:
    try:
        number = max(0, int(value or 0))
    except (TypeError, ValueError):
        number = 0
    if number >= 10000:
        return f"{number / 10000:.1f}w"
    if number >= 1000:
        return f"{number / 1000:.1f}k"
    return str(number)


def _safe_review_image_url(value: Any) -> str:
    """Allow only confirmed HTTPS Qidian/Yuewen image CDN hosts."""
    candidate = str(value or "").strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    if not candidate or len(candidate) > 2048:
        return ""
    try:
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        return ""
    if port not in (None, 443):
        return ""
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in REVIEW_IMAGE_HOST_SUFFIXES):
        return ""
    return candidate


def _review_avatar(review: dict[str, Any], *, author: bool = False, compact: bool = False) -> str:
    """Render a remote avatar/frame with an always-present initial fallback."""
    user_name = str(review.get("userName") or review.get("authorName") or "书友")
    initial = html.escape(user_name[:1] or "书")
    classes = ["comment-avatar"]
    if author or review.get("authorSay"):
        classes.append("author")
    if compact:
        classes.append("compact")
    avatar = _safe_review_image_url(review.get("avatar") or review.get("headImageUrl"))
    frame = _safe_review_image_url(review.get("avatarFrame"))
    photo = (
        f'<img class="avatar-photo" src="{html.escape(avatar, quote=True)}" alt="" '
        'loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.hidden=true">'
        if avatar
        else ""
    )
    frame_image = (
        f'<img class="avatar-frame" src="{html.escape(frame, quote=True)}" alt="" '
        'loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.hidden=true">'
        if frame
        else ""
    )
    return (
        f'<span class="{" ".join(classes)}" title="{html.escape(user_name, quote=True)}">'
        f'<span class="avatar-fallback">{initial}</span>{photo}{frame_image}</span>'
    )


def _official_title_image(title: dict[str, Any], *, class_name: str) -> str:
    """Render one complete title image; the artwork already contains its text."""
    image = _safe_review_image_url(title.get("image"))
    if not image:
        return ""
    name = str(title.get("name") or "用户头衔").strip()
    escaped_name = html.escape(name, quote=True)
    return (
        f'<span class="{class_name}" title="{escaped_name}">'
        f'<img src="{html.escape(image, quote=True)}" alt="{escaped_name}" loading="lazy" '
        'decoding="async" referrerpolicy="no-referrer" onerror="this.hidden=true"></span>'
    )


def _review_identity_tags(review: dict[str, Any], *, author: bool = False) -> str:
    """Render author, position, and de-duplicated title metadata."""
    tags: list[str] = []
    if author or review.get("authorSay"):
        tags.append('<span class="author-badge">作家</span>')

    raw_titles = review.get("titles") if isinstance(review.get("titles"), list) else []
    titles = [item for item in raw_titles if isinstance(item, dict)]
    if not titles:
        titles = [
            {"name": str(name)}
            for name in review.get("badges", [])
            if str(name).strip()
        ] if isinstance(review.get("badges"), list) else []

    position = str(review.get("position") or "").strip()
    seen_names: set[str] = set()
    if position:
        position_title = next(
            (title for title in titles if str(title.get("name") or "").strip() == position),
            {},
        )
        position_image = _official_title_image(position_title, class_name="position-title-image")
        tags.append(position_image or f'<span class="position-badge">{html.escape(position)}</span>')
        seen_names.add(position)

    for title in titles:
        name = str(title.get("name") or "").strip()
        if name and name in seen_names:
            continue
        image_html = _official_title_image(title, class_name="title-image")
        if image_html:
            tags.append(image_html)
        elif name:
            tags.append(f'<span class="title-badge">{html.escape(name)}</span>')
        else:
            continue
        if name:
            seen_names.add(name)
    return f'<span class="identity-tags">{"".join(tags)}</span>' if tags else ""


def _review_related_position(review: dict[str, Any]) -> str:
    """Render the replied-to user's official position image when available."""
    position = str(review.get("relatedPosition") or "").strip()
    if not position:
        return ""
    raw_titles = review.get("relatedTitles") if isinstance(review.get("relatedTitles"), list) else []
    position_title = next(
        (
            title
            for title in raw_titles
            if isinstance(title, dict) and str(title.get("name") or "").strip() == position
        ),
        {},
    )
    position_image = _official_title_image(position_title, class_name="related-position-image")
    return position_image or f'<span class="related-position">{html.escape(position)}</span>'


def _review_content(value: Any) -> str:
    """Escape review text and render Qidian's confirmed 1-64 icon set."""
    escaped = html.escape(str(value or ""))

    def render_emoticon(match: re.Match[str]) -> str:
        icon_id = int(match.group(1))
        if 1 <= icon_id <= 64:
            icon_url = REVIEW_EMOTICON_CDN.format(icon_id)
            return (
                f'<img class="comment-emoticon" src="{icon_url}" alt="表情" '
                f'title="起点表情 {icon_id}" loading="lazy" decoding="async" '
                'referrerpolicy="no-referrer">'
            )
        return (
            '<span class="comment-emoticon-fallback" '
            f'title="起点表情 {icon_id}">表情</span>'
        )

    return _INLINE_EMOTICON_RE.sub(
        render_emoticon,
        escaped,
    )


def _review_media(review: dict[str, Any]) -> str:
    """Render a confirmed image/GIF URL without proxying plugin data."""
    image_url = _safe_review_image_url(review.get("imageUrl"))
    preview_url = _safe_review_image_url(review.get("imagePreview"))
    media_url = image_url or preview_url
    if not media_url:
        return ""
    return (
        '<div class="comment-media-wrap">'
        f'<img class="comment-media" src="{html.escape(media_url, quote=True)}" alt="评论图片" '
        'loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.hidden=true">'
        '</div>'
    )


def _reply_row(reply: dict[str, Any], *, target_name: str) -> str:
    """Render one compact reply using the same rich identity contract."""
    reply_name = str(reply.get("userName") or "书友")
    reply_target = str(reply.get("replyToUserName") or target_name)
    target_position = _review_related_position(reply)
    content = _review_content(reply.get("content"))
    text = f'<p>{content}</p>' if content else ""
    return (
        '<div class="reply-line">'
        + _review_avatar(reply, compact=True)
        + '<div class="reply-body"><div class="reply-heading">'
        f'<span class="reply-author">{html.escape(reply_name)}</span>'
        + _review_identity_tags(reply)
        + '<span class="reply-arrow">回复</span>'
        f'<span class="reply-target">{html.escape(reply_target)}</span>{target_position}'
        + '</div>'
        + text
        + _review_media(reply)
        + '</div></div>'
    )


def _review_reply_context(review: dict[str, Any]) -> str:
    """Keep reply target context when a reply is rendered as its own card."""
    target_name = str(review.get("replyToUserName") or "").strip()
    if not target_name:
        return ""
    target_position = _review_related_position(review)
    return (
        '<div class="comment-reply-context"><span>回复</span>'
        f'<strong>{html.escape(target_name)}</strong>{target_position}</div>'
    )


def _review_card(
    review: dict[str, Any],
    *,
    author: bool = False,
    review_view_url: str = "",
    link_to_paragraph: bool = False,
    allow_reply_detail: bool = True,
) -> str:
    user_name = str(review.get("userName") or "书友")
    content = str(review.get("content") or "")
    review_time = str(review.get("reviewTime") or review.get("createTime") or "")
    replies = review.get("replies") if isinstance(review.get("replies"), list) else []
    replies = [reply for reply in replies if isinstance(reply, dict)]
    reply_rows = []
    for reply in replies:
        reply_rows.append(_reply_row(reply, target_name=user_name))
    reply_stack = ""
    reply_total = max(len(reply_rows), int(review.get("replyCount") or 0))
    if reply_rows:
        toggle = ""
        if len(reply_rows) > 1 or reply_total > 1:
            open_label = f"展开 {_count_label(reply_total)} 条回复"
            toggle = (
                '<button class="reply-toggle" type="button" data-reply-toggle aria-expanded="false" '
                f'data-open-label="{html.escape(open_label, quote=True)}" data-close-label="收起回复">'
                f'<span class="reply-toggle-label">{html.escape(open_label)}</span>'
                '<span aria-hidden="true">⌄</span></button>'
            )
        reply_stack = (
            '<div class="reply-stack"><div class="reply-surface">'
            + "".join(reply_rows)
            + toggle
            + '</div></div>'
        )

    detail_links: list[str] = []
    review_id = _review_id(review)
    try:
        paragraph_id = int(review.get("paragraphId", -1))
    except (TypeError, ValueError):
        paragraph_id = -1
    if review_view_url and link_to_paragraph and paragraph_id >= 0:
        query = urlencode({"tab": "paragraph", "paragraphId": paragraph_id})
        detail_links.append(
            f'<a class="comment-detail-link" href="{html.escape(review_view_url, quote=True)}?{query}">查看该段评论</a>'
        )
    if review_view_url and allow_reply_detail and review_id and reply_total > 0:
        query_values: dict[str, Any] = {"tab": "paragraph", "rootReviewId": review_id}
        if paragraph_id >= -1:
            query_values["paragraphId"] = paragraph_id
        query = urlencode(query_values)
        detail_links.append(
            f'<a class="comment-detail-link" href="{html.escape(review_view_url, quote=True)}?{query}">查看 {reply_total} 条回复</a>'
        )
    detail_row = f'<div class="comment-detail-row">{"".join(detail_links)}</div>' if detail_links else ""

    content_html = _review_content(content)
    text_html = f'<p class="comment-text">{content_html}</p>' if content_html else ""
    review_attr = f' data-review-id="{html.escape(review_id, quote=True)}"' if review_id else ""
    return (
        f'<article class="comment-item"{review_attr}>'
        + _review_avatar(review, author=author)
        + '<div class="comment-body">'
        + '<div class="comment-head">'
        + f'<div class="comment-identity"><strong>{html.escape(user_name)}</strong>'
        + _review_identity_tags(review, author=author)
        + '</div>'
        + f'<time>{html.escape(review_time)}</time></div>'
        + _review_reply_context(review)
        + text_html
        + _review_media(review)
        + '<div class="comment-meta">'
        + f'<span>赞 {_count_label(review.get("likeNum"))}</span>'
        + f'<span>回复 {_count_label(review.get("replyCount"))}</span>'
        + '</div>'
        + reply_stack
        + detail_row
        + '</div></article>'
    )


def _empty_state(message: str) -> str:
    return f'<p class="empty-state">{html.escape(message)}</p>'


def _folded_list(
    items: list[str],
    *,
    list_id: str,
    visible_count: int,
    empty_message: str,
    open_label: str = "展开更多",
    close_label: str = "收起",
    auto_load: bool = False,
) -> str:
    if not items:
        return _empty_state(empty_message)
    visible_count = max(1, visible_count)
    toggle = ""
    if len(items) > visible_count:
        auto_toggle_attr = ' data-auto-fold-toggle="true"' if auto_load else ""
        toggle = (
            f'<button class="fold-toggle" type="button" data-fold-toggle="{html.escape(list_id, quote=True)}" '
            f'{auto_toggle_attr} '
            f'data-open-label="{html.escape(open_label, quote=True)}" '
            f'data-close-label="{html.escape(close_label, quote=True)}">{html.escape(open_label)}</button>'
        )
    auto_list_attr = ' data-auto-load-list="true"' if auto_load else ""
    return (
        f'<div class="fold-list" id="{html.escape(list_id, quote=True)}" data-fold-list{auto_list_attr} '
        f'data-visible-count="{visible_count}">'
        + "".join(items)
        + '</div>'
        + toggle
    )


def _pagination_nav(
    payload: dict[str, Any],
    *,
    review_view_url: str,
    query: dict[str, Any],
    cursor: bool = False,
    auto_load: bool = False,
    list_id: str = "",
) -> str:
    page = max(1, int(payload.get("page") or 1))
    page_size = max(1, int(payload.get("pageSize") or 10))
    has_more = bool(payload.get("hasMore"))
    links: list[str] = []
    if page > 1:
        previous = {**query, "page": page - 1, "pageSize": page_size}
        if cursor:
            previous["cursorId"] = 0
        links.append(
            f'<a data-previous-page href="{html.escape(review_view_url, quote=True)}?{urlencode(previous)}">上一页</a>'
        )
    if has_more:
        following = {
            **query,
            "page": int(payload.get("nextPage") or page + 1),
            "pageSize": page_size,
        }
        if cursor:
            following["cursorId"] = int(payload.get("nextCursorId") or 0)
        links.append(
            f'<a data-next-page href="{html.escape(review_view_url, quote=True)}?{urlencode(following)}">加载更多</a>'
        )
    if not links:
        return ""
    auto_attr = (
        f' data-auto-pagination="true" data-list-id="{html.escape(list_id, quote=True)}"'
        if auto_load
        else ""
    )
    return f'<nav class="pagination-row"{auto_attr} aria-label="评论分页">{"".join(links)}</nav>'


def _paragraph_groups(
    reviews: dict[str, Any],
    *,
    review_view_url: str,
    selected_paragraph_id: int | None,
    paragraph_detail: dict[str, Any] | None,
) -> str:
    groups = [
        item
        for item in reviews.get("hotParagraphReviews", [])
        if isinstance(item, dict) and (item.get("matchedText") or item.get("paragraphText"))
    ]
    if selected_paragraph_id is not None:
        groups = [item for item in groups if int(item.get("paragraphId", -1)) == selected_paragraph_id]
    if not groups:
        return _empty_state("当前章节没有可可靠定位的页热评")

    rendered: list[str] = []
    for item in groups:
        paragraph_id = int(item.get("paragraphId", 0) or 0)
        comment_count = int(
            item.get("commentCount")
            or item.get("totalCommentCount")
            or item.get("hotCommentCount")
            or 0
        )
        detail_comments = []
        if selected_paragraph_id == paragraph_id and isinstance(paragraph_detail, dict):
            detail_comments = paragraph_detail.get("comments") or []
            comment_count = max(comment_count, int(paragraph_detail.get("totalCount") or 0))
        comments = (
            detail_comments
            if selected_paragraph_id == paragraph_id and isinstance(paragraph_detail, dict)
            else item.get("topReviews") or []
        )
        comments = [review for review in comments if isinstance(review, dict)]
        is_detail = selected_paragraph_id == paragraph_id and isinstance(paragraph_detail, dict)
        query = urlencode({"tab": "paragraph", "paragraphId": paragraph_id})
        comment_html = _folded_list(
            [_review_card(review, review_view_url=review_view_url) for review in comments],
            list_id=f"paragraph-comments-{paragraph_id}",
            visible_count=10 if is_detail else 2,
            empty_message="该热段暂未返回评论正文",
            open_label="加载更多评论" if is_detail else "展开更多评论",
            close_label="收起评论",
            auto_load=is_detail,
        )
        rendered.append(
            f'<article class="paragraph-group" data-paragraph-id="{paragraph_id}">'
            f'<p class="paragraph-quote">“{html.escape(str(item.get("matchedText") or item.get("paragraphText") or ""))}”</p>'
            '<div class="paragraph-summary">'
            f'<strong>官方段落 {paragraph_id}</strong>'
            f'<span class="hot-count">热评 {_count_label(comment_count)}</span></div>'
            + comment_html
            + (
                ""
                if selected_paragraph_id == paragraph_id
                else f'<a class="paragraph-more" href="{html.escape(review_view_url, quote=True)}?{query}">查看该段全部评论</a>'
            )
            + '</article>'
        )
    body = _folded_list(
        rendered,
        list_id="hot-paragraph-groups",
        visible_count=10,
        empty_message="当前章节没有可可靠定位的页热评",
        open_label="加载更多热门段落",
        close_label="收起热门段落",
        auto_load=True,
    )
    if selected_paragraph_id is not None and isinstance(paragraph_detail, dict):
        body += _pagination_nav(
            paragraph_detail,
            review_view_url=review_view_url,
            query={"tab": "paragraph", "paragraphId": selected_paragraph_id},
            auto_load=True,
            list_id=f"paragraph-comments-{selected_paragraph_id}",
        )
    return body


def _page_hot_review_list(
    detail: dict[str, Any],
    *,
    review_view_url: str,
) -> str:
    comments = [item for item in detail.get("comments", []) if isinstance(item, dict)]
    body = _folded_list(
        [
            _review_card(
                review,
                review_view_url=review_view_url,
                link_to_paragraph=True,
            )
            for review in comments
        ],
        list_id="page-hot-comments",
        visible_count=10,
        empty_message="当前页暂未返回热评",
        open_label="加载更多热评",
        close_label="收起当前批次热评",
        auto_load=True,
    )
    paragraph_ids = detail.get("paragraphIds") or []
    paragraph_ids_text = ",".join(str(value) for value in paragraph_ids)
    return body + _pagination_nav(
        detail,
        review_view_url=review_view_url,
        query={"tab": "paragraph", "paragraphIds": paragraph_ids_text},
        auto_load=True,
        list_id="page-hot-comments",
    )


def _reply_detail_list(
    detail: dict[str, Any],
    *,
    review_view_url: str,
) -> str:
    root = detail.get("rootReview") if isinstance(detail.get("rootReview"), dict) else None
    replies = [item for item in detail.get("replies", []) if isinstance(item, dict)]
    items = []
    if root is not None:
        items.append(_review_card(root, review_view_url=review_view_url, allow_reply_detail=False))
    items.extend(
        _review_card(reply, review_view_url=review_view_url, allow_reply_detail=False)
        for reply in replies
    )
    body = _folded_list(
        items,
        list_id="reply-detail-comments",
        visible_count=6,
        empty_message="该评论暂未返回回复",
        open_label="展开当前批次回复",
        close_label="收起当前批次回复",
    )
    return body + _pagination_nav(
        detail,
        review_view_url=review_view_url,
        query={
            "tab": "paragraph",
            "rootReviewId": detail.get("rootReviewId") or "",
        },
        cursor=True,
    )


_REVIEW_CSS = """
:root{color-scheme:light;font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;letter-spacing:0;--paper:#fbfcfc;--ink:#202a33;--muted:#6f7c86;--faint:#98a3ab;--line:#dce2e6;--line-soft:#e9edef;--blue:#3f7398;--blue-soft:#edf4f8;--green:#39765e;--green-soft:#edf7f2;--rose:#a15462}*{box-sizing:border-box}body{margin:0;min-width:320px;min-height:100dvh;background:var(--paper);color:var(--ink)}button{font:inherit;letter-spacing:0}.review-sheet{width:min(720px,100%);margin:0 auto;background:var(--paper)}.sheet-handle{width:36px;height:4px;margin:9px auto 3px;border-radius:999px;background:#cbd3d8}.sheet-header{display:flex;align-items:center;justify-content:space-between;min-height:58px;padding:5px 20px 8px}.sheet-title strong{display:block;font-size:16px}.sheet-title span{display:block;margin-top:3px;color:var(--faint);font-size:11px}.review-tabs{display:grid;grid-template-columns:repeat(3,1fr);padding:0 16px;border-top:1px solid var(--line-soft);border-bottom:1px solid var(--line)}.review-tab{position:relative;min-height:46px;border:0;background:transparent;color:var(--muted);cursor:pointer;font-size:13px;font-weight:600}.review-tab[aria-selected=true]{color:var(--ink)}.review-tab[aria-selected=true]::after{content:"";position:absolute;right:18%;bottom:-1px;left:18%;height:2px;background:var(--blue)}.review-tab small{margin-left:4px;color:var(--faint);font-size:10px}.sheet-content{overflow-y:auto}.review-panel{display:none;padding:0 20px 20px}.review-panel.active{display:block}.scope-row{display:flex;align-items:center;justify-content:space-between;min-height:48px;border-bottom:1px solid var(--line-soft);color:var(--muted);font-size:12px}.scope-row strong{color:var(--blue);font-size:12px}.comment-item{display:grid;grid-template-columns:34px minmax(0,1fr);gap:11px;padding:16px 0;border-bottom:1px solid var(--line-soft)}.comment-avatar{display:inline-flex;width:34px;height:34px;align-items:center;justify-content:center;border-radius:50%;background:#e8edf0;color:#4f626f;font-size:11px;font-weight:700}.comment-avatar.author{background:var(--green-soft);color:var(--green)}.comment-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.comment-head strong{font-size:12px}.comment-head time{color:var(--faint);font-size:10px}.author-badge{margin-left:6px;padding:2px 5px;border-radius:4px;background:var(--green-soft);color:var(--green);font-size:9px}.comment-text{margin:7px 0 0;color:#34424c;font-size:13px;line-height:1.65}.comment-meta{display:flex;gap:14px;margin-top:8px;color:var(--faint);font-size:10px}.comment-detail-row{display:flex;flex-wrap:wrap;gap:12px;margin-top:9px}.comment-detail-link{color:var(--blue);font-size:10px;font-weight:600;text-decoration:none}.reply-stack{position:relative;margin-top:12px;padding-bottom:11px}.reply-stack::before,.reply-stack::after{content:"";position:absolute;right:7px;bottom:4px;left:7px;height:24px;border:1px solid #dbe3e7;border-radius:6px;background:#edf1f3}.reply-stack::after{right:13px;bottom:0;left:13px;background:#e5ebee}.reply-stack.open{padding-bottom:0}.reply-stack.open::before,.reply-stack.open::after{opacity:0}.reply-surface{position:relative;z-index:1;overflow:hidden;border:1px solid #d7e0e5;border-radius:6px;background:#f5f8f9}.reply-line{padding:9px 11px;color:#56656f;font-size:11px;line-height:1.55}.reply-line+.reply-line{display:none;border-top:1px solid #e2e8eb}.reply-stack.open .reply-line{display:block}.reply-line p{margin:3px 0 0;color:#3c4a54}.reply-author{color:var(--blue);font-weight:700}.reply-target{color:#725d87;font-weight:600}.reply-arrow{margin:0 5px;color:var(--faint)}.reply-toggle{display:flex;width:100%;min-height:32px;align-items:center;justify-content:space-between;padding:0 11px;border:0;border-top:1px solid #e2e8eb;background:#f0f4f6;color:#526f82;cursor:pointer;font-size:10px;font-weight:600}.fold-toggle{display:block;width:100%;min-height:36px;border:0;border-top:1px solid var(--line-soft);background:transparent;color:var(--blue);cursor:pointer;font-size:11px;font-weight:600}.pagination-row{display:flex;justify-content:center;gap:12px;padding:14px 0 2px}.pagination-row a{min-width:88px;padding:8px 12px;border:1px solid var(--line);border-radius:6px;color:var(--blue);font-size:11px;font-weight:600;text-align:center;text-decoration:none}.paragraph-group{padding:15px 0 8px;border-bottom:1px solid var(--line-soft)}.paragraph-quote{margin:0;padding-left:11px;border-left:2px solid #a9bfcc;color:#586873;font-family:"Songti SC",SimSun,serif;font-size:12px;line-height:1.6}.paragraph-summary{display:flex;align-items:center;justify-content:space-between;margin-top:9px}.paragraph-summary strong{font-size:12px}.hot-count{color:var(--rose);font-size:11px;font-weight:700}.paragraph-more{display:inline-block;margin:12px 0 4px;color:var(--blue);font-size:11px;text-decoration:none}.empty-state{padding:24px 0;color:var(--faint);font-size:12px;text-align:center}@media(max-width:640px){.review-panel{padding-right:16px;padding-left:16px}}
.review-sheet{display:flex;height:100dvh;flex-direction:column}.sheet-content{min-height:0;flex:1}
.comment-body{min-width:0}.comment-avatar{position:relative;flex:none;overflow:visible}.avatar-fallback{position:relative;z-index:0}.avatar-photo{position:absolute;z-index:1;inset:0;width:100%;height:100%;border-radius:50%;object-fit:cover;background:#e8edf0}.avatar-frame{position:absolute;z-index:2;top:-4px;left:-4px;width:calc(100% + 8px);height:calc(100% + 8px);object-fit:contain;pointer-events:none}.comment-avatar.compact{width:24px;height:24px;font-size:9px}.comment-avatar.compact .avatar-frame{top:-3px;left:-3px;width:calc(100% + 6px);height:calc(100% + 6px)}.comment-head{align-items:flex-start}.comment-identity{display:flex;min-width:0;align-items:center;flex-wrap:wrap;gap:5px}.comment-identity strong{overflow-wrap:anywhere}.identity-tags{display:inline-flex;align-items:center;flex-wrap:wrap;gap:4px}.position-badge,.related-position,.title-badge{display:inline-flex;min-height:18px;align-items:center;gap:3px;padding:1px 5px;border-radius:4px;font-size:9px;font-weight:600;line-height:1.3}.position-badge{background:var(--green-soft);color:var(--green)}.related-position{margin-left:3px;background:#f0edf5;color:#725d87}.title-badge{border:1px solid #dce3e7;background:#f7f9fa;color:#5d6b75}.title-badge img{width:14px;height:14px;object-fit:contain}.comment-text,.reply-line p{overflow-wrap:anywhere;word-break:break-word;white-space:pre-wrap}.comment-emoticon{display:inline-block;width:22px;height:22px;object-fit:contain;vertical-align:middle}.comment-emoticon-fallback{display:inline-flex;min-height:20px;align-items:center;padding:1px 5px;border:1px solid #dce3e7;border-radius:4px;background:#f3f6f7;color:#687984;font-size:10px;vertical-align:middle}.comment-media-wrap{margin-top:9px}.comment-media{display:block;width:auto;max-width:min(280px,100%);max-height:320px;border:1px solid var(--line-soft);border-radius:6px;background:#f2f5f6;object-fit:contain}.reply-line{grid-template-columns:24px minmax(0,1fr);gap:8px}.reply-body{min-width:0}.reply-heading{display:flex;align-items:center;flex-wrap:wrap;gap:3px}.reply-heading .identity-tags{gap:3px}.reply-line p{margin:4px 0 0}.reply-line .comment-media{max-width:min(200px,100%);max-height:220px}@media(max-width:640px){.comment-media{max-height:240px}.reply-line .comment-media{max-height:180px}}
[hidden]{display:none!important}
.comment-reply-context{display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-top:5px;color:var(--faint);font-size:10px}.comment-reply-context strong{color:#725d87;font-size:10px}
.position-title-image,.title-image,.related-position-image{display:inline-flex;height:18px;align-items:center}.position-title-image img,.title-image img,.related-position-image img{display:block;width:auto;height:18px;max-width:100px;object-fit:contain}.related-position-image{margin-left:3px}
.load-status{display:block;width:100%;min-height:38px;border:0;background:transparent;color:var(--faint);font-size:11px;text-align:center}.load-status.error{color:var(--rose);cursor:pointer}
"""


_REVIEW_SCRIPT = r"""
const tabs = [...document.querySelectorAll("[data-tab]")];
const panels = [...document.querySelectorAll("[data-panel]")];
const scrollRoot = document.querySelector(".sheet-content");
const loadedUrls = new Set();
let loading = false;
let observer;

function activePanel() {
  return document.querySelector(".review-panel.active");
}

function applyFold(list, open) {
  const limit = Number(list.dataset.visibleCount || 1);
  [...list.children].forEach((item, index) => {
    item.hidden = !open && index >= limit;
  });
  list.dataset.open = String(open);
}

function bindReplyToggles(root = document) {
  root.querySelectorAll("[data-reply-toggle]").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      const stack = button.closest(".reply-stack");
      const open = !stack.classList.contains("open");
      stack.classList.toggle("open", open);
      button.setAttribute("aria-expanded", String(open));
      button.querySelector(".reply-toggle-label").textContent = open
        ? button.dataset.closeLabel
        : button.dataset.openLabel;
    });
  });
}

function ensureStatus(panel) {
  let status = panel.querySelector(":scope > .load-status");
  if (!status) {
    status = document.createElement("button");
    status.type = "button";
    status.className = "load-status";
    status.hidden = true;
    status.addEventListener("click", () => {
      if (status.classList.contains("error")) loadNext(panel);
    });
  }
  panel.append(status);
  return status;
}

function setStatus(panel, text, state = "") {
  const status = ensureStatus(panel);
  status.textContent = text;
  status.hidden = !text;
  status.disabled = state !== "error";
  status.classList.toggle("error", state === "error");
}

function revealAutoFold(button) {
  const panel = button.closest(".review-panel");
  const list = document.getElementById(button.dataset.foldToggle);
  if (!list) return;
  const items = [...list.children];
  const batchSize = Number(list.dataset.visibleCount || 10);
  const visibleCount = items.filter((item) => !item.hidden).length;
  const nextLimit = Math.min(items.length, visibleCount + batchSize);
  items.forEach((item, index) => { item.hidden = index >= nextLimit; });
  const complete = nextLimit >= items.length;
  list.dataset.open = String(complete);
  if (complete) button.remove();
  if (complete && !nextLink(panel)) setStatus(panel, "没有更多了", "end");
  arm();
}

function bindFoldToggles(root = document) {
  root.querySelectorAll("[data-fold-toggle]").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      if (button.dataset.autoFoldToggle) {
        revealAutoFold(button);
        return;
      }
      const list = document.getElementById(button.dataset.foldToggle);
      const open = list.dataset.open !== "true";
      applyFold(list, open);
      button.textContent = open ? button.dataset.closeLabel : button.dataset.openLabel;
    });
  });
}

function nextLink(panel) {
  return panel?.querySelector("[data-auto-pagination] [data-next-page]") || null;
}

function loadTarget(panel) {
  return panel?.querySelector("[data-auto-fold-toggle]")
    || panel?.querySelector("[data-auto-pagination]")
    || null;
}

function itemKey(element) {
  if (element.dataset.reviewId) return `review:${element.dataset.reviewId}`;
  if (element.dataset.paragraphId) return `paragraph:${element.dataset.paragraphId}`;
  return "";
}

function appendUnique(currentList, sourceList) {
  const known = new Set([...currentList.children].map(itemKey).filter(Boolean));
  let appended = 0;
  [...sourceList.children].forEach((item) => {
    const key = itemKey(item);
    if (key && known.has(key)) return;
    currentList.append(item.cloneNode(true));
    if (key) known.add(key);
    appended += 1;
  });
  return appended;
}

async function loadNext(panel = activePanel()) {
  if (!panel || loading) return;
  const foldButton = panel.querySelector("[data-auto-fold-toggle]");
  if (foldButton) {
    revealAutoFold(foldButton);
    return;
  }
  const link = nextLink(panel);
  if (!link || loadedUrls.has(link.href)) return;

  loading = true;
  observer.disconnect();
  setStatus(panel, "加载中...", "loading");
  let failed = false;
  try {
    const response = await fetch(link.href);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const source = new DOMParser().parseFromString(await response.text(), "text/html");
    const sourcePanel = source.querySelector(`[data-panel="${CSS.escape(panel.dataset.panel)}"]`);
    const currentNav = panel.querySelector("[data-auto-pagination]");
    const listId = currentNav?.dataset.listId || "";
    const currentList = listId ? document.getElementById(listId) : null;
    const sourceList = listId ? source.getElementById(listId) : null;
    if (!sourcePanel || !currentList || !sourceList) throw new Error("评论分页结构不完整");

    appendUnique(currentList, sourceList);
    bindReplyToggles(currentList);
    bindFoldToggles(currentList);
    loadedUrls.add(link.href);

    panel.querySelector("[data-auto-pagination]")?.remove();
    const newNav = sourcePanel.querySelector("[data-auto-pagination]")?.cloneNode(true);
    newNav?.querySelectorAll("[data-previous-page]").forEach((item) => item.remove());
    if (newNav?.querySelector("[data-next-page]")) panel.append(newNav);
    setStatus(panel, nextLink(panel) ? "" : "没有更多了", "end");
  } catch (error) {
    failed = true;
    setStatus(panel, "网络错误，点击重试", "error");
  } finally {
    loading = false;
    if (!failed) arm();
  }
}

function arm() {
  observer.disconnect();
  const target = loadTarget(activePanel());
  if (target) observer.observe(target);
}

function activate(name, resetScroll = false) {
  tabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.tab === name)));
  panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
  if (resetScroll) scrollRoot.scrollTop = 0;
  arm();
}

document.querySelectorAll("[data-fold-list]").forEach((list) => applyFold(list, false));
bindReplyToggles();
bindFoldToggles();
observer = new IntersectionObserver(
  (entries) => {
    if (entries.some((entry) => entry.isIntersecting)) loadNext();
  },
  { root: scrollRoot, rootMargin: "0px 0px 120px 0px" },
);
tabs.forEach((tab) => tab.addEventListener("click", () => activate(tab.dataset.tab, true)));
activate("__ACTIVE_TAB__");
"""


def render_chapter_reviews_html(
    *,
    chapter_title: str,
    reviews: dict[str, Any],
    review_view_url: str,
    active_tab: str = "chapter",
    selected_paragraph_id: int | None = None,
    paragraph_detail: dict[str, Any] | None = None,
    page_hot_detail: dict[str, Any] | None = None,
    chapter_detail: dict[str, Any] | None = None,
    reply_detail: dict[str, Any] | None = None,
) -> str:
    """Render the review sheet, limiting drill-down pages to paragraph reviews."""
    paragraph_only = any(
        isinstance(detail, dict)
        for detail in (paragraph_detail, page_hot_detail, reply_detail)
    )
    if paragraph_only:
        active_tab = "paragraph"
    active_tab = active_tab if active_tab in {"author", "chapter", "paragraph"} else "chapter"
    author_reviews = [item for item in reviews.get("authorReviews", []) if isinstance(item, dict)]
    chapter_reviews = _dedupe_reviews(reviews.get("chapterEndHot"), reviews.get("chapterEnd"))
    matched_paragraphs = [
        item
        for item in reviews.get("hotParagraphReviews", [])
        if isinstance(item, dict) and (item.get("matchedText") or item.get("paragraphText"))
    ]
    paragraph_count = sum(
        int(item.get("commentCount") or item.get("totalCommentCount") or 0)
        for item in matched_paragraphs
    )
    summary = reviews.get("summary") if isinstance(reviews.get("summary"), dict) else {}
    chapter_count = int(summary.get("chapterEndCount") or len(chapter_reviews))
    total_reviews = int(summary.get("totalReviews") or len(chapter_reviews) + paragraph_count)
    author_html = _folded_list(
        [_review_card(review, author=True) for review in author_reviews],
        list_id="author-comments",
        visible_count=1,
        empty_message="本章没有作家补充",
        open_label="展开更多作家说",
        close_label="收起作家说",
    )
    chapter_page_reviews = (
        [item for item in chapter_detail.get("comments", []) if isinstance(item, dict)]
        if isinstance(chapter_detail, dict)
        else chapter_reviews
    )
    chapter_html = _folded_list(
        [_review_card(review, review_view_url=review_view_url) for review in chapter_page_reviews],
        list_id="chapter-comments",
        visible_count=10,
        empty_message="本章暂未返回章末评论",
        open_label="加载更多本章说",
        close_label="收起本章说",
        auto_load=True,
    )
    chapter_page_payload = chapter_detail if isinstance(chapter_detail, dict) else {
        "page": 1,
        "pageSize": 10,
        "hasMore": len(reviews.get("chapterEnd") or []) < chapter_count,
        "nextPage": 2,
    }
    chapter_html += _pagination_nav(
        chapter_page_payload,
        review_view_url=review_view_url,
        query={"tab": "chapter"},
        auto_load=True,
        list_id="chapter-comments",
    )
    if isinstance(reply_detail, dict):
        paragraph_html = _reply_detail_list(reply_detail, review_view_url=review_view_url)
        paragraph_scope_label = "评论回复"
        paragraph_scope_count = int(reply_detail.get("totalCount") or 0)
    elif isinstance(page_hot_detail, dict):
        paragraph_html = _page_hot_review_list(page_hot_detail, review_view_url=review_view_url)
        paragraph_scope_label = "当前页热评"
        paragraph_scope_count = int(page_hot_detail.get("totalCount") or 0)
    else:
        paragraph_html = _paragraph_groups(
            reviews,
            review_view_url=review_view_url,
            selected_paragraph_id=selected_paragraph_id,
            paragraph_detail=paragraph_detail,
        )
        paragraph_scope_label = (
            f"官方段落 {selected_paragraph_id}"
            if selected_paragraph_id is not None
            else f"{len(matched_paragraphs)} 个热门段落"
        )
        paragraph_scope_count = (
            int(paragraph_detail.get("totalCount") or 0)
            if isinstance(paragraph_detail, dict)
            else paragraph_count
        )

    def tab(name: str, label: str, count: int) -> str:
        selected = "true" if active_tab == name else "false"
        return f'<button class="review-tab" type="button" role="tab" data-tab="{name}" aria-selected="{selected}">{label}<small>{_count_label(count)}</small></button>'

    def panel(name: str, label: str, count: int, body: str) -> str:
        active = " active" if active_tab == name else ""
        return (
            f'<section class="review-panel{active}" data-panel="{name}" role="tabpanel">'
            f'<div class="scope-row"><span>{label}</span><strong>{_count_label(count)} 条</strong></div>'
            + body
            + '</section>'
        )

    tabs_html = ""
    panels_html = panel("paragraph", paragraph_scope_label, paragraph_scope_count, paragraph_html)
    if not paragraph_only:
        tabs_html = (
            '<div class="review-tabs" role="tablist" aria-label="评论分类">'
            + tab("author", "作家说", len(author_reviews))
            + tab("chapter", "本章说", chapter_count)
            + tab("paragraph", "段评说", paragraph_count)
            + '</div>'
        )
        panels_html = (
            panel("author", "作者补充", len(author_reviews), author_html)
            + panel("chapter", "本章说", chapter_count, chapter_html)
            + panels_html
        )

    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(chapter_title)} · 本章评论</title><style>{_REVIEW_CSS}</style></head><body>'
        '<main class="review-sheet"><div class="sheet-handle" aria-hidden="true"></div>'
        '<header class="sheet-header"><div class="sheet-title"><strong>本章评论</strong>'
        f'<span>{html.escape(chapter_title)} · {_count_label(total_reviews)} 条</span></div></header>'
        + tabs_html
        + '<div class="sheet-content">'
        + panels_html
        + '</div></main><script>'
        + _REVIEW_SCRIPT.replace("__ACTIVE_TAB__", active_tab)
        + '</script></body></html>'
    )
