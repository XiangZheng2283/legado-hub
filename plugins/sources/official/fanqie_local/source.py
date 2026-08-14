"""
fanqie_local — 番茄小说（本地下载器桥接）

通过本地运行的 Tomato-Novel-Downloader Web API 接入番茄小说内容。

配置（环境变量）：
  FANQIE_LOCAL_BASE        下载器地址，默认 http://127.0.0.1:18423
  FANQIE_LOCAL_PASSWD      下载器密码，默认空
  FANQIE_LOCAL_TIMEOUT     等待整本下载完成的超时秒数，默认 900
"""

from __future__ import annotations

import asyncio
import io
import os
import posixpath
import re
import time
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

TOMATO_BASE = os.environ.get("FANQIE_LOCAL_BASE", "http://127.0.0.1:18423").rstrip("/")
TOMATO_PASSWD = os.environ.get("FANQIE_LOCAL_PASSWD", "")
DOWNLOAD_TIMEOUT_S = int(os.environ.get("FANQIE_LOCAL_TIMEOUT", "900"))
_POLL_S = 5
_STATUS_CACHE_TTL = 60
_ORDER_CACHE_TTL = 300

# ── 进程级缓存 ────────────────────────────────────────────────────────────────
# 生产环境的 PluginContext.cache_get/cache_set 是空实现，且调度器每章新建 ctx，
# 导致每次章节请求都会重新下载和解析整本 EPUB。
# 这里用进程级字典绕过这一限制：以 rel_path 为键缓存原始字节和解析结果。
# 键格式：(rel_path,) -> (expires_at: float, value)
_PROC_CACHE: dict[str, tuple[float, Any]] = {}


def _proc_cache_get(key: str) -> Any:
    entry = _PROC_CACHE.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        _PROC_CACHE.pop(key, None)
        return None
    return value


def _proc_cache_set(key: str, value: Any, ttl: float) -> None:
    _PROC_CACHE[key] = (time.monotonic() + ttl, value)
    # 简单 LRU 截断：超过 64 条时丢弃最旧的一半
    if len(_PROC_CACHE) > 64:
        oldest = sorted(_PROC_CACHE.items(), key=lambda kv: kv[1][0])
        for k, _ in oldest[:32]:
            _PROC_CACHE.pop(k, None)


class Source:
    id = "fanqie_local"
    name = "番茄小说（本地下载器）"
    contract_version = "1.0"
    last_modified = "2026-08-14"

    # ── 生命周期 ──────────────────────────────────────────────────

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        if page > 1:
            return []
        keyword = keyword.strip()
        if not keyword:
            return []
        try:
            data = await ctx.access.http.fetch_json(
                f"{TOMATO_BASE}/api/search",
                params={"q": keyword},
                headers=_headers(),
                timeout=15,
            )
        except Exception as e:
            ctx.trace("search", url=f"{TOMATO_BASE}/api/search", message=f"连接下载器失败: {e}")
            raise

        # 下载器以 no-official-api 模式编译时搜索不可用，error 字段会说明原因
        if data.get("error"):
            ctx.trace("search", message=f"下载器搜索不可用: {data['error']}")
            raise RuntimeError(f"番茄下载器搜索不可用: {data['error']}")

        results = []
        for item in data.get("items") or []:
            book_id = str(item.get("book_id") or "").strip()
            if not book_id:
                continue
            raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
            tags = _pick_tags(raw)
            category = _pick_string(raw, "category", "category_name", "book_category", "classify")
            kind_parts = [part for part in [category, *tags] if part]
            results.append({
                "sourceId": self.id,
                "name": str(item.get("title") or ""),
                "author": str(item.get("author") or ""),
                "bookUrl": _book_url(book_id),
                "coverUrl": "",
                "intro": _pick_string(
                    raw,
                    "abstract",
                    "book_abstract_v2",
                    "book_abstract",
                    "description",
                    "intro",
                    "summary",
                ),
                "kind": "/".join(dict.fromkeys(kind_parts)),
                "lastChapter": _pick_string(
                    raw,
                    "last_chapter_title",
                    "latest_catalog_title",
                    "lastItemTitle",
                ),
                "wordCount": _format_word_count(
                    _pick_value(raw, "word_number", "word_count", "word_cnt", "words")
                ),
                "extra": {"book_id": book_id},
            })
        return results

    async def detail(self, ctx, book_url: str) -> dict:
        book_id = _extract_id(book_url)
        data = await _preview(ctx, book_id)
        tags = data.get("tags") or []
        kind_parts = []
        if data.get("category"):
            kind_parts.append(str(data["category"]))
        for t in tags:
            s = str(t).strip()
            if s and s not in kind_parts:
                kind_parts.append(s)
        if data.get("finished") is True:
            kind_parts.append("完结")
        elif data.get("finished") is False:
            kind_parts.append("连载")
        wc = data.get("word_count")
        word_count_str = f"{int(wc) // 10000}万字" if wc and int(wc) >= 10000 else (str(wc) if wc else "")
        return {
            "sourceId": self.id,
            "name": str(data.get("book_name") or ""),
            "author": str(data.get("author") or ""),
            "bookUrl": book_url,
            "coverUrl": "",
            "intro": str(data.get("description") or ""),
            "kind": "/".join(kind_parts),
            "lastChapter": str(data.get("last_chapter_title") or ""),
            "wordCount": word_count_str,
            "tocUrl": book_url,
            "extra": {"book_id": book_id},
        }

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        """仅在下载 job 完成后，从最终 EPUB/TXT 成品解析目录。"""
        book_id = _extract_id(toc_url)
        order = await self._chapter_order(ctx, book_id)
        result = []
        for idx, (ch_id, title) in enumerate(order, start=1):
            result.append({
                "sourceId": self.id,
                "index": idx,
                "title": title,
                "chapterUrl": _chapter_url(book_id, ch_id),
            })
        return result

    async def chapter(self, ctx, chapter_url: str) -> dict:
        """从整本成品的解析缓存中返回指定章节。"""
        book_id, ch_id = _parse_chapter_url(chapter_url)

        # 读取缓存的章节顺序（已包含 ensure_downloaded 逻辑）
        order = await self._chapter_order(ctx, book_id)
        if not order:
            return _pending_chapter(chapter_url, "下载未完成，请稍后重试。")

        # 根据 ch_id 找到对应的序号
        ch_index = None
        for idx, (cid, _title) in enumerate(order):
            if cid == ch_id:
                ch_index = idx
                break
        if ch_index is None:
            return _pending_chapter(chapter_url, "章节未找到，可能尚未下载。")

        rel_path = await _find_book_file_rel(ctx, book_id)
        if not rel_path:
            return _pending_chapter(chapter_url, "下载文件未找到，请稍后重试。")

        chapters = await self._get_chapters(ctx, rel_path)
        if ch_index >= len(chapters):
            return _pending_chapter(chapter_url, "章节索引超出范围，请稍后重试。")

        _title, content = chapters[ch_index]
        return {
            "sourceId": self.id,
            "chapterUrl": chapter_url,
            "title": _title,
            "content": content,
            "format": "text",
        }

    async def chapter_reviews(self, ctx, chapter_url: str) -> dict:
        book_id, ch_id = _parse_chapter_url(chapter_url)
        order = await self._chapter_order(ctx, book_id)
        chapter_match = next(
            ((idx, title) for idx, (candidate, title) in enumerate(order) if candidate == ch_id),
            None,
        )
        if chapter_match is None:
            return _empty_reviews("章节未找到")
        _chapter_index, chapter_title = chapter_match

        rel_path = await _find_book_file_rel(ctx, book_id)
        if not rel_path or not rel_path.lower().endswith(".epub"):
            return _empty_reviews("成品不是 EPUB，无法读取段评")

        raw = await self._get_book_bytes(ctx, rel_path)
        if not raw:
            return _empty_reviews("EPUB 读取失败")
        return _extract_epub_reviews(raw, chapter_title, ch_id)

    async def paragraph_say(
        self,
        ctx,
        chapter_url: str,
        paragraph_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        reviews = await self.chapter_reviews(ctx, chapter_url)
        all_reviews = reviews.get("paragraphs", {}).get(str(int(paragraph_id)), [])
        if not isinstance(all_reviews, list):
            all_reviews = []
        page = max(1, int(page))
        page_size = min(50, max(1, int(page_size)))
        start = (page - 1) * page_size
        comments = all_reviews[start : start + page_size]
        total = len(all_reviews)
        for item in reviews.get("hotParagraphReviews", []):
            if isinstance(item, dict) and int(item.get("paragraphId", -1)) == int(paragraph_id):
                total = max(total, int(item.get("totalCommentCount") or total))
                break
        return {
            "paragraphId": int(paragraph_id),
            "comments": comments,
            "totalCount": total,
            "embeddedCount": len(all_reviews),
            "page": page,
            "pageSize": page_size,
            "hasMore": start + len(comments) < len(all_reviews),
            "nextPage": page + 1 if start + len(comments) < len(all_reviews) else None,
        }

    async def chapter_review_media(self, ctx, chapter_url: str, asset_ref: str) -> dict:
        book_id, _ch_id = _parse_chapter_url(chapter_url)
        rel_path = await _find_book_file_rel(ctx, book_id)
        if not rel_path or not rel_path.lower().endswith(".epub"):
            return {"bytes": b"", "mime": "", "debug": {"error": "EPUB not found"}}
        raw = await self._get_book_bytes(ctx, rel_path)
        try:
            member = _normalize_epub_member(asset_ref)
        except ValueError:
            return {"bytes": b"", "mime": "", "debug": {"error": "invalid EPUB image reference"}}
        if not member.startswith("OEBPS/images/"):
            return {"bytes": b"", "mime": "", "debug": {"error": "image reference outside EPUB images"}}
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            try:
                info = archive.getinfo(member)
            except KeyError:
                return {"bytes": b"", "mime": "", "debug": {"error": "image not found"}}
            if info.file_size <= 0 or info.file_size > _MAX_EPUB_IMAGE_BYTES:
                return {"bytes": b"", "mime": "", "debug": {"error": "image too large"}}
            data = archive.read(member)
        mime = _image_mime(data)
        if mime not in _ALLOWED_IMAGE_MIMES:
            return {"bytes": b"", "mime": "", "debug": {"error": "unsupported image format"}}
        return {"bytes": data, "mime": mime}

    # ── 内部辅助 ──────────────────────────────────────────────────

    async def _chapter_order(self, ctx, book_id: str) -> list[tuple[str, str]]:
        """返回整本成品中的有序章节 ID 和标题。"""
        cache_key = f"fanqie_order:{book_id}"
        cached = ctx.cache_get(cache_key) or _proc_cache_get(cache_key)
        if cached:
            return cached

        rel_path = await _find_book_file_rel(ctx, book_id)
        if not rel_path:
            rel_path = await self._ensure_downloaded(ctx, book_id)
        if not rel_path:
            return []

        chapters = await self._get_chapters(ctx, rel_path)
        order = [(str(i + 1), title) for i, (title, _content) in enumerate(chapters)]
        ctx.cache_set(cache_key, order, _ORDER_CACHE_TTL)
        _proc_cache_set(cache_key, order, _ORDER_CACHE_TTL)
        return order

    async def _get_book_bytes(self, ctx, rel_path: str) -> bytes:
        cache_key = f"fanqie_book_bytes:{rel_path}"
        # 先查 ctx（单次请求内有效），再查进程级缓存（跨 context 有效）。
        cached = ctx.cache_get(cache_key) or _proc_cache_get(cache_key)
        if cached is not None:
            return cached

        # 两个程序共处一机：save_dir 就是本进程可直接访问的真实目录。
        # 直接读文件，完全不走 HTTP，也不需要回退；禁止 rel_path 越出 save_dir。
        status = await _downloader_status(ctx)
        save_dir = str(status.get("save_dir") or "").strip()
        local_path = _safe_local_book_path(save_dir, rel_path)
        raw = await asyncio.get_event_loop().run_in_executor(
            None, local_path.read_bytes
        )

        ctx.cache_set(cache_key, raw, _ORDER_CACHE_TTL)
        _proc_cache_set(cache_key, raw, _ORDER_CACHE_TTL)
        return raw

    async def _get_chapters(self, ctx, rel_path: str) -> list[tuple[str, str]]:
        cache_key = f"fanqie_chapters:{rel_path}"
        cached = ctx.cache_get(cache_key) or _proc_cache_get(cache_key)
        if cached is not None:
            return cached
        try:
            raw = await self._get_book_bytes(ctx, rel_path)
            if rel_path.lower().endswith(".epub"):
                chapters = await _split_epub_async(raw)
            else:
                chapters = _split_txt(ctx.decode_text(raw))
        except Exception as e:
            ctx.trace("chapter", message=f"fetch book file failed: {e}")
            return []
        ctx.cache_set(cache_key, chapters, _ORDER_CACHE_TTL)
        _proc_cache_set(cache_key, chapters, _ORDER_CACHE_TTL)
        return chapters

    async def _ensure_downloaded(self, ctx, book_id: str) -> str | None:
        """
        触发下载 job，轮询等待 Done，自动回应 book_name/format 选择，
        返回最终成品的 rel_path 或 None。
        """
        # 先看有没有已完成的 job，有则只定位这个完成任务的文件。
        existing = await _find_done_job(ctx, book_id)
        if existing:
            return await _find_book_file_rel(ctx, book_id, job_id=existing)

        # 查询是否已有正在运行的 job（下载器同时只允许 1 个活跃任务）
        try:
            data = await ctx.access.http.fetch_json(
                f"{TOMATO_BASE}/api/jobs",
                params={"all": "true"},
                headers=_headers(),
                timeout=10,
            )
        except Exception as e:
            ctx.trace("chapter", message=f"list jobs error: {e}")
            return None

        active_job_id: int | None = None
        for job in data.get("items") or []:
            if (
                str(job.get("book_id", "")) == book_id
                and job.get("state") not in ("done", "failed", "canceled")
            ):
                active_job_id = job.get("id")
                break

        if active_job_id is None:
            # 没有活跃任务，创建新 job
            try:
                resp = await ctx.access.http.fetch_json(
                    f"{TOMATO_BASE}/api/jobs",
                    method="POST",
                    json={"book_id": book_id},
                    headers={**_headers(), "Content-Type": "application/json"},
                    timeout=15,
                )
            except Exception as e:
                ctx.trace("chapter", message=f"create job error: {e}")
                return None
            active_job_id = resp.get("id")
            if not active_job_id:
                # 创建时发生竞态，再查一次活跃任务
                active_job_id = await _wait_for_active_job(ctx, book_id)
                if not active_job_id:
                    return None

        job_id = active_job_id
        deadline = time.monotonic() + DOWNLOAD_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(_POLL_S)
            try:
                jobs = await ctx.access.http.fetch_json(
                    f"{TOMATO_BASE}/api/jobs",
                    params={"id": str(job_id), "all": "true"},
                    headers=_headers(),
                    timeout=10,
                )
            except Exception:
                continue

            items = jobs.get("items") or []
            if not items:
                continue
            job = items[0]
            state = job.get("state", "")

            # 保持下载器配置的默认书名和 EPUB 格式；完整 EPUB 才包含段评与媒体。
            if job.get("book_name_options"):
                await _submit_choice(ctx, job_id, "book_name", None)
            if job.get("format_options"):
                await _submit_choice(ctx, job_id, "format", "epub")

            if state == "done":
                return await _find_book_file_rel(ctx, book_id, job_id=job_id)
            if state in ("failed", "canceled"):
                ctx.trace("chapter", message=f"job {job_id} ended with state={state}: {job.get('message')}")
                return None

        ctx.trace("chapter", message=f"job {job_id} did not finish before timeout")
        return None


# ─────────────────────────────────────────────────────────────────
# 模块级工具函数
# ─────────────────────────────────────────────────────────────────

def _headers() -> dict:
    h = {"Accept": "application/json"}
    if TOMATO_PASSWD:
        h["x-tomato-password"] = TOMATO_PASSWD
    return h


def _book_url(book_id: str) -> str:
    return f"{TOMATO_BASE}/__fanqie__/{book_id}"


def _chapter_url(book_id: str, ch_id: str) -> str:
    return f"{TOMATO_BASE}/__fanqie__/{book_id}/{ch_id}"


def _cover_url(book_id: str) -> str:
    return f"{TOMATO_BASE}/api/preview-cover-by-book/{book_id}"


def _pick_value(data: dict, *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def _pick_string(data: dict, *keys: str) -> str:
    value = _pick_value(data, *keys)
    return str(value).strip() if value is not None else ""


def _pick_tags(data: dict) -> list[str]:
    value = _pick_value(data, "tags", "book_tags", "tag", "categories", "classify_tags")
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,，/|]", value) if part.strip()]
    return []


def _format_word_count(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        count = int(float(value))
    except (TypeError, ValueError):
        return str(value).strip()
    return f"{count // 10000}万字" if count >= 10000 else str(count)


def _extract_id(url: str) -> str:
    """从 bookUrl / tocUrl 里取出 book_id（路径最后一段）。"""
    return url.rstrip("/").split("/")[-1]


def _safe_local_book_path(save_dir: str, rel_path: str) -> Path:
    root = Path(str(save_dir or "").strip()).expanduser().resolve()
    if not str(root):
        raise ValueError("番茄下载器未返回 save_dir")
    normalized = str(rel_path or "").replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("下载器文件路径无效")
    candidate = (root / Path(normalized)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("下载器文件路径越出 save_dir") from exc
    return candidate


def _parse_chapter_url(url: str) -> tuple[str, str]:
    """chapterUrl: .../book_id/ch_id  → (book_id, ch_id)"""
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]


def _pending_chapter(chapter_url: str, msg: str) -> dict:
    return {
        "sourceId": "fanqie_local",
        "chapterUrl": chapter_url,
        "title": "",
        "content": "",
        "format": "text",
        "debug": {"error": msg},
    }


async def _preview(ctx, book_id: str) -> dict:
    """调用 /api/preview/:book_id，缓存 _STATUS_CACHE_TTL 秒。"""
    cache_key = f"fanqie_preview:{book_id}"
    cached = ctx.cache_get(cache_key)
    if cached:
        return cached
    data = await ctx.access.http.fetch_json(
        f"{TOMATO_BASE}/api/preview/{book_id}",
        headers=_headers(),
        timeout=20,
    )
    ctx.cache_set(cache_key, data, _STATUS_CACHE_TTL)
    return data


async def _downloader_status(ctx) -> dict:
    cache_key = "fanqie_downloader_status"
    cached = ctx.cache_get(cache_key) or _proc_cache_get(cache_key)
    if cached:
        return cached
    data = await ctx.access.http.fetch_json(
        f"{TOMATO_BASE}/api/status",
        headers=_headers(),
        timeout=10,
    )
    if not str(data.get("save_dir") or "").strip():
        raise RuntimeError("番茄下载器未返回 save_dir")
    ctx.cache_set(cache_key, data, _STATUS_CACHE_TTL)
    _proc_cache_set(cache_key, data, _STATUS_CACHE_TTL)
    return data


async def _library_snapshot(ctx, path: str = "", *, refresh: bool = False) -> dict:
    params = {"start": "true" if refresh else "false"}
    if path:
        params["path"] = path
    for attempt in range(10):
        data = await ctx.access.http.fetch_json(
            f"{TOMATO_BASE}/api/library",
            params=params,
            headers=_headers(),
            timeout=10,
        )
        if not data.get("running"):
            return data
        params["start"] = "false"
        if attempt < 9:
            await asyncio.sleep(0.2)
    return data


async def _find_book_file_rel(
    ctx,
    book_id: str,
    *,
    job_id: int | None = None,
) -> str | None:
    """按指定完成 job 的书名定位根目录 EPUB/TXT，兼容旧的 book_id 目录。"""
    job = await _find_done_job_info(ctx, book_id, job_id=job_id)
    if not job:
        return None
    title = str(job.get("title") or "").strip()
    try:
        await _downloader_status(ctx)
        root = await _library_snapshot(ctx, refresh=True)
    except Exception as exc:
        ctx.trace("toc", message=f"library scan failed: {exc}")
        return None

    files = [
        item for item in root.get("items") or []
        if item.get("kind") == "file" and item.get("ext") in {"txt", "epub"}
    ]
    if title:
        exact = [item for item in files if _file_stem(item.get("name", "")) == title]
        if exact:
            exact.sort(key=lambda item: (item.get("ext") != "epub", -(item.get("modified_ms") or 0)))
            return str(exact[0].get("rel_path") or "") or None

    target_dir = next(
        (
            item.get("rel_path", "")
            for item in root.get("items") or []
            if item.get("kind") == "dir" and item.get("name", "") == book_id
        ),
        "",
    )
    if target_dir:
        try:
            sub = await _library_snapshot(ctx, target_dir, refresh=True)
        except Exception:
            sub = {}
        nested = [
            item for item in sub.get("items") or []
            if item.get("kind") == "file" and item.get("ext") in {"txt", "epub"}
        ]
        if nested:
            nested.sort(key=lambda item: (item.get("ext") != "epub", -(item.get("modified_ms") or 0)))
            return str(nested[0].get("rel_path") or "") or None

    return None


def _file_stem(name: str) -> str:
    return str(name).rsplit(".", 1)[0]


async def _find_done_job_info(
    ctx,
    book_id: str,
    *,
    job_id: int | None = None,
) -> dict | None:
    try:
        data = await ctx.access.http.fetch_json(
            f"{TOMATO_BASE}/api/jobs",
            params={"all": "true"},
            headers=_headers(),
            timeout=10,
        )
    except Exception:
        return None
    matches = [
        job for job in data.get("items") or []
        if (
            str(job.get("book_id", "")) == book_id
            and job.get("state") == "done"
            and (job_id is None or str(job.get("id")) == str(job_id))
        )
    ]
    if not matches:
        return None
    return max(matches, key=lambda job: int(job.get("updated_ms") or 0))


async def _find_done_job(ctx, book_id: str) -> int | None:
    job = await _find_done_job_info(ctx, book_id)
    return job.get("id") if job else None


async def _wait_for_active_job(ctx, book_id: str) -> int | None:
    """当 create_job 返回 429（已有活跃任务），轮询并返回对应 job_id。"""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        try:
            data = await ctx.access.http.fetch_json(
                f"{TOMATO_BASE}/api/jobs",
                params={"all": "true"},
                headers=_headers(),
                timeout=10,
            )
        except Exception:
            continue
        for job in data.get("items") or []:
            if str(job.get("book_id", "")) == book_id:
                return job.get("id")
    return None


async def _submit_choice(ctx, job_id: int, kind: str, value: str | None) -> None:
    """自动回应 book_name / format 选择（None = 下载器使用默认第一项）。"""
    try:
        await ctx.access.http.fetch_json(
            f"{TOMATO_BASE}/api/jobs/{job_id}/{kind}",
            method="POST",
            json={"value": value},
            headers={**_headers(), "Content-Type": "application/json"},
            timeout=10,
        )
    except Exception as e:
        ctx.trace("chapter", message=f"submit {kind} choice error: {e}")


def _normalize_epub_member(path: str) -> str:
    value = unquote(str(path or "")).replace("\\\\", "/")
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("EPUB member path is absolute")
    normalized = posixpath.normpath(value)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise ValueError("EPUB member path escapes archive")
    return normalized


def _resolve_epub_href(base_path: str, href: str) -> tuple[str, str]:
    parsed = urlsplit(unquote(str(href or "")))
    if parsed.scheme or parsed.netloc:
        raise ValueError("EPUB href must be relative")
    member = _normalize_epub_member(
        posixpath.join(posixpath.dirname(base_path), parsed.path)
    )
    return member, parsed.fragment


def _epub_spine(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
    rootfile = container.find(".//{*}rootfile")
    if rootfile is None or not rootfile.get("full-path"):
        raise ValueError("EPUB container 未声明 OPF")

    opf_path = _normalize_epub_member(rootfile.get("full-path", ""))
    opf = ElementTree.fromstring(archive.read(opf_path))
    manifest = {
        item.get("id", ""): item.get("href", "")
        for item in opf.findall(".//{*}manifest/{*}item")
        if item.get("id") and item.get("href")
    }
    result = []
    for itemref in opf.findall(".//{*}spine/{*}itemref"):
        href = manifest.get(itemref.get("idref", ""), "")
        if href:
            member, _fragment = _resolve_epub_href(opf_path, href)
            result.append((member, href))
    return result


def _epub_chapter_candidates(
    spine: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    named = [
        item for item in spine
        if re.fullmatch(r"chapter_\d+\.xhtml?", posixpath.basename(item[1]), re.I)
    ]
    return named or [
        item for item in spine
        if not posixpath.basename(item[1]).lower().startswith("aux_")
        and posixpath.basename(item[1]).lower()
        not in {"table-of-contents.html", "toc.xhtml", "nav.xhtml"}
    ]


def _xhtml_soup(archive: zipfile.ZipFile, path: str) -> BeautifulSoup:
    return BeautifulSoup(archive.read(path), "html.parser")


def _clean_chapter_document(soup: BeautifulSoup) -> BeautifulSoup:
    body = soup.body or soup
    for node in body.select(
        "h1, h2, script, style, nav, header, footer, "
        ".back-to-comments, .back-to-chapter, .segment-link, .seg-count"
    ):
        node.decompose()
    return body


def _chapter_heading(soup: BeautifulSoup) -> Any:
    body = soup.body or soup
    return body.find(["h1", "h2"]) or soup.find("title")


def _parse_xhtml_bytes(xhtml: bytes) -> tuple[str, str] | None:
    """解析单个 xhtml 文件字节，返回 (title, content) 或 None（跳过段评页等）。
    纯 CPU 操作，可安全在线程池中并发执行。"""
    soup = BeautifulSoup(xhtml, "html.parser")
    heading = _chapter_heading(soup)
    title = heading.get_text(" ", strip=True) if heading else ""
    if not title or title.endswith(" - 段评"):
        return None
    body = _clean_chapter_document(soup)
    content = "\n".join(body.stripped_strings).strip()
    return (title, content)


async def _split_epub_async(raw: bytes) -> list[tuple[str, str]]:
    """解析整本 EPUB，对各章 xhtml 并发跑 BS4（线程池）。"""
    loop = asyncio.get_event_loop()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        candidates = _epub_chapter_candidates(_epub_spine(archive))
        indexed_chunks: list[tuple[int, bytes]] = [
            (i, archive.read(path)) for i, (path, _href) in enumerate(candidates)
        ]

    tasks = {
        asyncio.ensure_future(loop.run_in_executor(None, _parse_xhtml_bytes, chunk)): index
        for index, chunk in indexed_chunks
    }
    results: list[tuple[int, tuple[str, str] | None]] = []
    pending = set(tasks)
    while pending:
        done, pending = await asyncio.wait(
            pending,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            results.append((tasks[task], task.result()))
    results.sort(key=lambda item: item[0])
    return [result for _index, result in results if result is not None]


def _parse_xhtml_document(soup: BeautifulSoup) -> tuple[str, str] | None:
    heading = _chapter_heading(soup)
    title = heading.get_text(" ", strip=True) if heading else ""
    if not title or title.endswith(" - 段评"):
        return None
    body = _clean_chapter_document(soup)
    return title, "\n".join(body.stripped_strings).strip()


def _split_epub(raw: bytes) -> list[tuple[str, str]]:
    """同步入口，供测试和离线工具使用。"""
    chapters: list[tuple[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        candidates = _epub_chapter_candidates(_epub_spine(archive))
        for path, _href in candidates:
            parsed = _parse_xhtml_document(_xhtml_soup(archive, path))
            if parsed is not None:
                chapters.append(parsed)
    return chapters


def _empty_reviews(error: str = "") -> dict:
    result = {
        "paragraphs": {},
        "chapterEnd": [],
        "chapterEndHot": [],
        "authorReviews": [],
        "hotParagraphReviews": [],
        "summary": {
            "totalParagraphs": 0,
            "totalReviews": 0,
            "paragraphsWithReviews": [],
            "paragraphStats": {},
            "chapterEndCount": 0,
            "hotParagraphCount": 0,
        },
    }
    if error:
        result["debug"] = {"error": error}
    return result


_MAX_EPUB_IMAGE_BYTES = 10 * 1024 * 1024
_ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _safe_epub_image_ref(
    archive: zipfile.ZipFile,
    base_member: str,
    src: str,
) -> str:
    member, fragment = _resolve_epub_href(base_member, src)
    if fragment or not member.startswith("OEBPS/images/"):
        return ""
    try:
        info = archive.getinfo(member)
    except KeyError:
        return ""
    if info.file_size <= 0 or info.file_size > _MAX_EPUB_IMAGE_BYTES:
        return ""
    data = archive.read(member)
    if _image_mime(data) not in _ALLOWED_IMAGE_MIMES:
        return ""
    return member


def _review_time(value: int) -> str:
    if value > 1_000_000_000_000:
        value //= 1000
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_comment_count(value: str) -> int:
    match = re.search(r"[（(]\s*(\d+)\s*[）)]", str(value or ""))
    return int(match.group(1)) if match else 0


def _chapter_link_index(
    archive: zipfile.ZipFile,
    chapter_member: str,
) -> tuple[dict[tuple[str, str], tuple[int, int]], dict[str, str]]:
    """Return (aux member/fragment -> (正文 p index, total), p id -> text)."""
    soup = _xhtml_soup(archive, chapter_member)
    links: dict[tuple[str, str], tuple[int, int]] = {}
    paragraph_texts: dict[str, str] = {}
    for index, node in enumerate(soup.select("body p")):
        paragraph_id = str(node.get("id") or "")
        if paragraph_id:
            body_copy = BeautifulSoup(str(node), "html.parser")
            for badge in body_copy.select(".seg-count"):
                badge.decompose()
            paragraph_texts[paragraph_id] = body_copy.get_text(" ", strip=True)
        anchor = node.select_one("a.seg-count[href]")
        if anchor is None:
            continue
        try:
            aux_member, fragment = _resolve_epub_href(chapter_member, str(anchor.get("href") or ""))
        except ValueError:
            continue
        if fragment:
            links[(aux_member, fragment)] = (index, _parse_comment_count(anchor.get_text(" ", strip=True)))
    return links, paragraph_texts


def _find_review_page_by_title(
    archive: zipfile.ZipFile,
    target_title: str,
) -> tuple[str, BeautifulSoup] | None:
    for path, _href in _epub_spine(archive):
        soup = _xhtml_soup(archive, path)
        heading = soup.find(["h1", "h2"])
        title = heading.get_text(" ", strip=True) if heading else ""
        if title == target_title:
            return path, soup
    return None


def _extract_epub_reviews(raw: bytes, chapter_title: str, chapter_id: str) -> dict:
    """Extract all embedded comments, using正文 seg-count soft links as authority."""
    try:
        chapter_number = max(0, int(chapter_id) - 1)
    except (TypeError, ValueError):
        chapter_number = -1
    page_targets: dict[tuple[str, str], tuple[int, int]] = {}
    paragraph_texts: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        spine = _epub_spine(archive)
        candidates = _epub_chapter_candidates(spine)
        if 0 <= chapter_number < len(candidates):
            chapter_member = candidates[chapter_number][0]
            try:
                page_targets, paragraph_texts = _chapter_link_index(archive, chapter_member)
            except Exception:
                page_targets = {}
        if not page_targets:
            return _empty_reviews("正文未找到该章段评软链接")
        pages: dict[str, BeautifulSoup] = {}
        if page_targets:
            for member, _fragment in page_targets:
                if member not in pages:
                    try:
                        pages[member] = _xhtml_soup(archive, member)
                    except KeyError:
                        continue

        paragraphs: dict[str, list[dict]] = {}
        hot: list[dict] = []
        total_comment_count = 0
        for member, soup in pages.items():
            for heading in soup.select("h3[id^='para-']"):
                match = re.fullmatch(r"para-(\d+)", str(heading.get("id") or ""))
                if not match:
                    continue
                para_fragment = str(heading.get("id"))
                target = page_targets.get((member, para_fragment))
                if page_targets and target is None:
                    continue
                paragraph_id = int(match.group(1))
                paragraph_index = target[0] if target is not None else paragraph_id
                total_count = target[1] if target is not None else 0
                paragraph_text_node = heading.select_one(".para-src")
                paragraph_text = (
                    paragraph_text_node.get_text(" ", strip=True).strip('"“”')
                    if paragraph_text_node else heading.get_text(" ", strip=True)
                )
                back_link = heading.find_next_sibling("div", class_="back-to-chapter")
                linked_p = ""
                if back_link is not None:
                    back_anchor = back_link.select_one("a[href]")
                    if back_anchor is not None:
                        try:
                            _member, fragment = _resolve_epub_href(member, str(back_anchor.get("href") or ""))
                            linked_p = fragment
                        except ValueError:
                            linked_p = ""
                if linked_p:
                    paragraph_text = paragraph_texts.get(linked_p, paragraph_text)
                review_list = heading.find_next_sibling("ol")
                if review_list is None:
                    continue
                reviews: list[dict] = []
                for review_index, item in enumerate(review_list.select("li.seg-item"), start=1):
                    meta_node = item.select_one("small.seg-meta")
                    meta_text = meta_node.get_text(" ", strip=True) if meta_node else ""
                    content_node = next(
                        (node for node in item.find_all("p") if not node.select_one("small.seg-meta")),
                        None,
                    )
                    content = content_node.get_text("\n", strip=True) if content_node else ""
                    if not content:
                        continue
                    user_match = re.search(r"作者：(.+?)(?:\s*\|\s*时间：|\s*\|\s*赞：|$)", meta_text)
                    time_match = re.search(r"时间：(\d+)", meta_text)
                    like_match = re.search(r"赞：(\d+)", meta_text)
                    review = {
                        "id": f"fanqie-local-{chapter_id}-{paragraph_id}-{review_index}",
                        "content": content,
                        "userName": user_match.group(1).strip() if user_match else "匿名",
                        "likeNum": int(like_match.group(1)) if like_match else 0,
                        "reviewTime": _review_time(int(time_match.group(1))) if time_match else "",
                        "paragraphId": paragraph_id,
                    }
                    avatar = meta_node.select_one("img.avatar[src]") if meta_node else None
                    if avatar is not None:
                        avatar_ref = _safe_epub_image_ref(archive, member, str(avatar.get("src") or ""))
                        if avatar_ref:
                            review["avatarRef"] = avatar_ref
                    image_refs = []
                    for image in item.select(".seg-images img[src]"):
                        image_ref = _safe_epub_image_ref(archive, member, str(image.get("src") or ""))
                        if image_ref and image_ref not in image_refs:
                            image_refs.append(image_ref)
                    if image_refs:
                        review["imageRefs"] = image_refs
                    reviews.append(review)
                if not reviews and not total_count:
                    continue
                key = str(paragraph_id)
                paragraphs[key] = reviews
                total_comment_count += total_count or len(reviews)
                hot.append({
                    "paragraphId": paragraph_id,
                    "paragraphText": paragraph_text,
                    "matchedText": paragraph_text,
                    "matchedParagraphIndex": paragraph_index,
                    "matchedParagraphCount": 1,
                    "matchStatus": "direct",
                    "matchConfidence": 1.0,
                    "commentCount": total_count or len(reviews),
                    "hotCommentCount": len(reviews),
                    "totalCommentCount": total_count or len(reviews),
                    "topReviews": reviews[:3],
                })

    stats = {key: len(value) for key, value in paragraphs.items()}
    embedded_total = sum(stats.values())
    result = _empty_reviews()
    result["paragraphs"] = paragraphs
    result["hotParagraphReviews"] = hot
    result["summary"] = {
        "totalParagraphs": len(paragraphs),
        "totalReviews": embedded_total,
        "embeddedReviews": embedded_total,
        "totalCommentCount": total_comment_count or embedded_total,
        "paragraphsWithReviews": sorted(int(key) for key in paragraphs),
        "paragraphStats": stats,
        "chapterEndCount": 0,
        "hotParagraphCount": len(hot),
    }
    return result


def _split_txt(text: str) -> list[tuple[str, str]]:
    """
    将番茄下载器输出的 txt 切割为 [(title, content), ...] 列表。

    番茄 txt 格式：每章以「第x章 xxxx」形式的行开头，x 不保证统一，
    也可能是序章/番外/楔子/后记/尾声等特殊章节标题。
    用宽松正则匹配章节分隔行，避免漏掉非标准编号。
    """
    chapter_head = re.compile(
        r"^(?:第[零一二三四五六七八九十百千万\d]+章|序章|楔子|番外|后记|尾声|完结感言|结尾)\s*.*$",
        re.MULTILINE,
    )

    boundaries: list[tuple[int, str]] = []
    for m in chapter_head.finditer(text):
        boundaries.append((m.start(), m.group(0).strip()))

    if not boundaries:
        # 没有找到任何章节头，把整个文本作为一章
        return [("正文", text.strip())]

    result: list[tuple[str, str]] = []
    for i, (start, title) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        newline_pos = text.find("\n", start)
        body_start = newline_pos + 1 if newline_pos != -1 and newline_pos < end else end
        content = text[body_start:end].strip()
        result.append((title, content))
    return result
