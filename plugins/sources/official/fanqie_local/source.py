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
import hashlib
import io
import json
import os
import posixpath
import re
import threading
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
        """按 bookid 目录纯本地读取，毫秒级、绝不因 preview/jobs 超时 404。

        需求：解析只看 fqdown 的 save_dir/<bookid>/ 目录（status.json +
        downloaded_chapters.jsonl + cover），与“是否下载完成”无关；epub/jobs
        只是完成度辅助判定，不参与阅读解析。preview 仅用缓存覆盖，绝不阻塞。
        """
        book_id = _extract_id(book_url)
        # preview 仅当已缓存（下载/后台预热过）时补充书名简介等，不发起网络。
        cached: dict = {}
        try:
            cached = ctx.cache_get(f"fanqie_preview:{book_id}") or {}
        except Exception:
            cached = {}
        if not isinstance(cached, dict):
            cached = {}

        # 本地 bookid 目录 = 唯一数据源（勿阻塞；读不动就返回占位而非 404）。
        info: dict = {}
        folder: Any = None
        journal: list = []
        try:
            status = await _downloader_status(ctx)
            folder = _local_book_dir(str(status.get("save_dir") or ""), book_id)
            info = _safe_json_load(folder / "status.json") or {}
            journal = _journal_entries(folder)
        except Exception:
            pass

        # 合并字段：cached preview / status.json / journal 谁有谁补。
        def pick(*keys: str) -> str:
            for key in keys:
                v = cached.get(key)
                if v:
                    return str(v)
                v = info.get(key)
                if v:
                    return str(v)
            return ""

        name = pick("book_name", "book_name")
        author = pick("author", "author")
        intro = pick("description", "description")
        category = pick("category", "category")
        last_chapter_title = pick("last_chapter_title", "last_chapter_title")
        if not last_chapter_title and journal:
            last_chapter_title = str(journal[-1][2] or "")

        kind_parts: list[str] = []
        if category:
            kind_parts.append(category)
        for src in (cached, info):
            for t in (src.get("tags") or []):
                s = str(t).strip()
                if s and s not in kind_parts:
                    kind_parts.append(s)
        finished = cached.get("finished", info.get("finished"))
        if finished is True:
            kind_parts.append("完结")
        elif finished is False:
            kind_parts.append("连载")

        wc = cached.get("word_count", info.get("word_count"))
        try:
            wc_int = int(wc)
        except (TypeError, ValueError):
            wc_int = 0
        word_count_str = (
            f"{wc_int // 10000}万字"
            if wc_int >= 10000
            else (str(wc) if wc else "")
        )

        extra: dict[str, Any] = {"book_id": book_id}
        if folder is not None:
            extra["download_count"] = len(journal)
            cover = _local_cover_path(folder)
            if cover is not None:
                extra["cover_local_path"] = str(cover)

        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": "",
            "intro": intro,
            "kind": "/".join(kind_parts),
            "lastChapter": last_chapter_title,
            "wordCount": word_count_str,
            "tocUrl": book_url,
            "extra": extra,
        }

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        """按本地增量落盘返回目录，下到哪给到哪。

        首次打开/尚未下载时（journal 为空）幂等触发下载 job（best-effort），
        目录随下载逐步补全；否则用户点不进章节，懒触发也永远不会发生（死锁）。
        """
        book_id = _extract_id(toc_url)
        order = await self._chapter_order(ctx, book_id)
        if not order:
            await _ensure_job_started(ctx, book_id)
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
        """按本地增量落盘返回指定章节正文（纯文本），下到哪返回哪。"""
        book_id, ch_id = _parse_chapter_url(chapter_url)
        try:
            ch_index = int(ch_id) - 1
        except (TypeError, ValueError):
            return _pending_chapter(chapter_url, "章节编号无效。")
        if ch_index < 0:
            return _pending_chapter(chapter_url, "章节编号无效。")

        try:
            status = await _downloader_status(ctx)
            folder = _local_book_dir(str(status.get("save_dir") or ""), book_id)
            entries = _chapter_entries(folder)
        except Exception:
            return _pending_chapter(chapter_url, "下载器状态不可用，请稍后重试。", retryable=True)

        # 命中即返回：常见路径不打 /api/jobs。
        if ch_index < len(entries):
            _x, _fid, title, content = entries[ch_index]
            if content:
                return {
                    "sourceId": self.id,
                    "chapterUrl": chapter_url,
                    "title": title,
                    "content": _clean_text(content),
                    "format": "text",
                }

        # 未命中：确保有下载 job 在跑（幂等、不等待、容忍 429 降级），随后可重试。
        await _ensure_job_started(ctx, book_id)
        return _pending_chapter(chapter_url, "章节下载中，请稍后重试。", retryable=True)

    async def chapter_reviews(self, ctx, chapter_url: str) -> dict:
        book_id, ch_id = _parse_chapter_url(chapter_url)
        try:
            ch_index = int(ch_id) - 1
        except (TypeError, ValueError):
            return _empty_reviews("章节编号无效。")
        if ch_index < 0:
            return _empty_reviews("章节编号无效。")

        try:
            status = await _downloader_status(ctx)
            folder = _local_book_dir(str(status.get("save_dir") or ""), book_id)
            entries = _chapter_entries(folder)
        except Exception:
            return _empty_reviews("下载器状态不可用。")

        if ch_index >= len(entries):
            return _empty_reviews("章节下载中，请稍后重试。")
        _x, fnqie_id, _title, _content = entries[ch_index]

        cache_path = folder / "segment_comments" / f"{fnqie_id}.json"
        cache = _safe_json_load(cache_path)
        if cache is None or not cache.get("paras"):
            return _empty_reviews("段评下载中，请稍后重试。")
        return _build_reviews_from_local(cache, ch_id, folder)

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
        # 新式：asset_ref 是本地 images/ 缓存的绝对路径（只读，不经上游）
        try:
            status = await _downloader_status(ctx)
            folder = _local_book_dir(str(status.get("save_dir") or ""), book_id)
            images_dir = (folder / "images").resolve()
            try:
                ref_path = Path(asset_ref).expanduser().resolve()
                ref_path.relative_to(images_dir)
            except ValueError:
                ref_path = None
            if ref_path is not None and ref_path.is_file():
                data = await asyncio.get_event_loop().run_in_executor(None, ref_path.read_bytes)
                mime = _image_mime(data)
                if mime in _ALLOWED_IMAGE_MIMES and 0 < len(data) <= _MAX_EPUB_IMAGE_BYTES:
                    return {"bytes": data, "mime": mime}
                return {"bytes": b"", "mime": "", "debug": {"error": "local image invalid"}}
        except Exception:
            pass
        # 旧式：EPUB 内嵌资源
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
        """按本地增量落盘返回有序 [(hub 章号, 标题)]，不依赖最终成品。"""
        cache_key = f"fanqie_order:{book_id}"
        # 只做请求内缓存（避免跨请求 5 分钟陈旧）：读小文件本就廉价。
        cached = ctx.cache_get(cache_key)
        if cached:
            return cached
        try:
            status = await _downloader_status(ctx)
            folder = _local_book_dir(str(status.get("save_dir") or ""), book_id)
            entries = _chapter_entries(folder)
        except Exception:
            return []
        order = [(str(i + 1), title) for i, (_x, _f, title, _c) in enumerate(entries)]
        ctx.cache_set(cache_key, order, _ORDER_CACHE_TTL)
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

# ────────────────────────────────────────────────────────────────
# 本地落盘增量读取（hub 侧，不依赖最终成品，也不修改下载器）
#
# 下载器按 book_id 在 save_dir/<book_id> 下增量写这些文件：
#   status.json                书籍元数据（普通写、非原子 → 容错重试读）
#   downloaded_chapters.jsonl  增量正文（append，容忍最后一行半截）
#   segment_comments/<id>.json 每章段评（原子写，读安全）
#   images/<sha1(url)><ext>    评论 / 头像媒体（只读缓存，绝不抓上游）
#   cover.png / cover.jpg ...  封面
# 本层只读这些，不需要整本成品，也不给下载器增加任何共享状态。
# ────────────────────────────────────────────────────────────────


def _local_book_dir(save_dir: str, book_id: str) -> Path:
    root = Path(str(save_dir or "").strip()).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"番茄下载器未返回有效 save_dir: {root}")
    folder = (root / book_id).resolve()
    try:
        folder.relative_to(root)
    except ValueError:
        raise ValueError(f"book_id 越出 save_dir: {book_id}") from None
    return folder


def _safe_json_load(path: Path, *, retries: int = 3, delay: float = 0.25) -> dict | None:
    """下载器 status.json 用普通写、可能读到半截 JSON；短重试等写方完成。"""
    for _ in range(retries):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except ValueError:
            time.sleep(delay)
    return None


_JOURNAL_CACHE: dict[str, "_BookJournalCache"] = {}
_JOURNAL_CACHE_GUARD = threading.Lock()


class _BookJournalCache:
    """按(书目录)的 downloaded_chapters.jsonl 增量缓存。

    fqdown 是**追加写**（append），hub 完全不需要整体落库。首次建好索引后，
    每次只读“上次读到 offset 之后追加的那一小段”并续上，改了 mtime/size 才刷，
    整份 JSONL 只在首见/截断时解析一遍 → 读取 O(1)，不随章节数膨胀（就绪的
    大书也不再卡）。读写都加同一把 per-book 锁，和下载器追加并发安全。
    """

    __slots__ = ("path", "lock", "offset", "entries", "mtime_ns", "size")

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.offset = 0
        self.entries: list[tuple[int, str, str, str]] = []
        self.mtime_ns = 0
        self.size = 0

    def refresh(self) -> list[tuple[int, str, str, str]]:
        with self.lock:
            try:
                st = self.path.stat()
            except OSError:
                self.entries = []
                self.offset = self.size = self.mtime_ns = 0
                return self.entries
            if st.st_mtime_ns == self.mtime_ns and st.st_size == self.size:
                return self.entries
            if st.st_size < self.offset or (
                st.st_size == self.offset and self.offset > 0
            ):
                # 被重写/截断（含同尺寸覆盖）或更小：丢弃旧索引全量重建。
                self.offset = 0
                self.entries = []
            try:
                if self.offset == 0:
                    data = self.path.read_bytes()
                else:
                    with self.path.open("rb") as f:
                        f.seek(self.offset)
                        data = f.read()
            except OSError:
                return self.entries
            # 只消费到最后一个 \n 之前的“完整行”，末尾半行（可能半个 UTF-8 字符）
            # 留到下次追加后再续读，避免把写了一半的行解进条目。
            nl = data.rfind(b"\n")
            if nl == -1:
                self.mtime_ns = st.st_mtime_ns
                self.size = st.st_size
                return self.entries
            complete = data[: nl + 1]
            if self.offset == 0:
                self.entries = []
            for line in complete.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or "\ufffd" in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                fid = str(rec.get("id") or "")
                if not fid:
                    continue
                self.entries.append(
                    (len(self.entries), fid, str(rec.get("title") or ""), str(rec.get("content") or ""))
                )
            self.offset += nl + 1
            self.mtime_ns = st.st_mtime_ns
            self.size = st.st_size
            return self.entries


def _cached_entries(folder: Path) -> list[tuple[int, str, str, str]]:
    """读 downloaded_chapters.jsonl 增量索引（共享内存式缓存 + 锁）。"""
    cache_key = str(folder.resolve())
    with _JOURNAL_CACHE_GUARD:
        cache = _JOURNAL_CACHE.get(cache_key)
        if cache is None:
            cache = _JOURNAL_CACHE.setdefault(
                cache_key, _BookJournalCache(folder / "downloaded_chapters.jsonl")
            )
    return cache.refresh()


def _journal_entries(folder: Path) -> list[tuple[int, str, str, str]]:
    """downloaded_chapters.jsonl → [(order, fnqie_id, title, content)]（走增量缓存）。"""
    return _cached_entries(folder)


def _status_fallback_entries(info: dict | None) -> list[tuple[int, str, str, str]]:
    """早期版本只有 status.json 的 downloaded map：fnqie_id → [title, content]（无增量文件）。"""
    fallback: list[tuple[int, str, str, str]] = []
    downloaded = (info or {}).get("downloaded") or {}
    if not isinstance(downloaded, dict):
        return fallback
    for key, value in downloaded.items():
        title = ""
        content = ""
        if isinstance(value, list) and value:
            title = str(value[0] or "")
            if len(value) > 1 and isinstance(value[1], str):
                content = value[1]
        elif isinstance(value, str):
            content = value
        fallback.append((len(fallback), str(key), title, content))
    return fallback


def _chapter_entries(folder: Path) -> list[tuple[int, str, str, str]]:
    """合并 journal 与 status 回退，返回有序 [(order, fnqie_id, title, content)]。"""
    entries = _journal_entries(folder)
    if entries:
        return entries
    return _status_fallback_entries(_safe_json_load(folder / "status.json"))


def _clean_text(html: str) -> str:
    """XHTML → 纯文本：段落/换行转行，剥标签，解码实体，坍缩空行。"""
    s = re.sub(
        r"<[^>]+>", "",
        html.replace("</p>", "\n").replace("</div>", "\n")
            .replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n"),
    )
    s = (s.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", "\"").replace("&#39;", "'").replace("&amp;", "&"))
    return "\n".join(line for line in (part.strip() for part in s.splitlines()) if line)


def _media_sha(url: str) -> str:
    """下载器按 sha1(url) 命名媒体缓存，须与该实现一致（images/<digest><ext>）。"""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


_MEDIA_EXTS = (".jpeg", ".jpg", ".png", ".gif", ".webp", ".avif", ".heic", ".heif")


def _media_base_dirs(folder: Path) -> list[Path]:
    """评论媒体可能的落盘目录：images/ 平铺，以及 images/ 下的直接子目录
    （如 images/comments、images/avatar —— 下载期 ReviewClient 可能用子目录）。
    只枚举第一层子目录，绝不递归，避免误扫其它内容。"""
    images_dir = folder / "images"
    bases: list[Path] = [images_dir]
    try:
        for child in images_dir.iterdir():
            if child.is_dir():
                bases.append(child)
    except OSError:
        pass
    return bases


def _cached_media_path(folder: Path, url: str) -> Path | None:
    """只读：返回该 URL 已缓存的本地完整路径；未缓存返回 None。绝不触发上游网络。"""
    if not url:
        return None
    # 下载器以 trim 后的 url 命名缓存（sha1(trim url)），须对齐。
    digest = _media_sha(url.strip())
    for base in _media_base_dirs(folder):
        for ext in _MEDIA_EXTS:
            candidate = base / f"{digest}{ext}"
            if candidate.is_file():
                return candidate
    return None


def _local_cover_path(folder: Path) -> Path | None:
    for name in ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp", "cover.gif"):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


async def _ensure_job_started(ctx, book_id: str) -> dict:
    """确保该 book 有一个下载 job：幂等（已有 job 任意态即复用，不重复创建）、不等待完成。

    返回 {"started": bool, "job_id": int | None, "disposition": str}
      disposition ∈ existing_running | existing_done | existing_failed | created | throttled | error
    - throttled：下载器单活跃任务（429）或创建被拒 → 暂时不可用，稍后重试。
    """
    base = {"started": False, "job_id": None, "disposition": "error"}

    # 1) 查已存在 job（幂等判断）
    try:
        data = await ctx.access.http.fetch_json(
            f"{TOMATO_BASE}/api/jobs", params={"all": "true"}, headers=_headers(), timeout=10,
        )
    except Exception as exc:
        ctx.trace("job", message=f"list jobs error: {exc}")
        return base
    for job in data.get("items") or []:
        if str(job.get("book_id", "")) == book_id:
            state = str(job.get("state") or "")
            jid = job.get("id")
            if state in ("queued", "running"):
                return {"started": True, "job_id": jid, "disposition": "existing_running"}
            if state == "done":
                return {"started": True, "job_id": jid, "disposition": "existing_done"}
            # failed / canceled：不自动重建，避免反复 POST 打下载器。
            return {"started": False, "job_id": jid, "disposition": "existing_failed"}

    # 2) 创建新 job；下载器单活跃任务，超限会 429（或网络错）→ 视为暂时不可用。
    try:
        resp = await ctx.access.http.fetch_json(
            f"{TOMATO_BASE}/api/jobs", method="POST", json={"book_id": book_id},
            headers={**_headers(), "Content-Type": "application/json"}, timeout=15,
        )
    except Exception as exc:
        ctx.trace("job", message=f"create job refused: {exc}")
        return base | {"disposition": "throttled"}

    jid = resp.get("id")
    if jid:
        return {"started": True, "job_id": jid, "disposition": "created"}

    # 3) 竞态：创建返回空（被抢先），再查一次活跃任务
    try:
        data = await ctx.access.http.fetch_json(
            f"{TOMATO_BASE}/api/jobs", params={"all": "true"}, headers=_headers(), timeout=10,
        )
    except Exception:
        return base | {"disposition": "throttled"}
    for job in data.get("items") or []:
        if str(job.get("book_id", "")) == book_id:
            state = str(job.get("state") or "")
            if state in ("queued", "running"):
                return {"started": True, "job_id": job.get("id"), "disposition": "existing_running"}
            if state == "done":
                return {"started": True, "job_id": job.get("id"), "disposition": "existing_done"}
    return base | {"disposition": "throttled"}


def _build_reviews_from_local(cache: dict, chapter_id: str, folder: Path) -> dict:
    """segment_comments/<fnqie_id>.json → 与 _extract_epub_reviews 同构的输出契约。"""
    paras_raw = cache.get("paras") or {}
    paragraphs: dict[str, list[dict]] = {}
    hot: list[dict] = []
    total_comment_count = 0

    for para_key, para in paras_raw.items():
        if not isinstance(para, dict):
            continue
        try:
            paragraph_id = int(para_key)
        except (TypeError, ValueError):
            continue
        try:
            total_count = int(para.get("count") or 0)
        except (TypeError, ValueError):
            total_count = 0
        detail = para.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        snippet = ""
        meta = detail.get("meta")
        if isinstance(meta, dict):
            snippet = str(meta.get("para_content") or "").strip()
        reviews_raw = detail.get("reviews")
        if not isinstance(reviews_raw, list):
            # 只有计数、无详情：登记空段（下游据此可知该段有评但未拉取）
            if not total_count:
                continue
            paragraphs[str(paragraph_id)] = []
            continue

        reviews: list[dict] = []
        for review_index, item in enumerate(reviews_raw, start=1):
            if not isinstance(item, dict):
                continue
            content = str(item.get("text") or "").strip()
            if not content:
                continue
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            images_urls = item.get("images")
            if not isinstance(images_urls, list):
                images_urls = []
            created_ts = item.get("created_ts")
            review: dict[str, Any] = {
                "id": f"fanqie-local-{chapter_id}-{paragraph_id}-{review_index}",
                "content": content,
                "userName": str(user.get("name") or "匿名").strip() or "匿名",
                "likeNum": int(item.get("digg_count") or 0),
                "reviewTime": _review_time(int(created_ts) if isinstance(created_ts, int) else 0),
                "paragraphId": paragraph_id,
            }
            # 头像：真实格式将 sha1(user.avatar) 落在 images/avatars/<sha1>.<ext>
            # （_cached_media_path 已含 images/ 平铺 + images/*/ 子目录），命中即回填 avatarRef。
            avatar_url = str(user.get("avatar") or "").strip()
            # 原始 CDN URL（客户端直载优先，fallback 用）；本地仅兜底。
            if avatar_url:
                review["avatarUrl"] = avatar_url
            avatar_path = _cached_media_path(folder, avatar_url) if avatar_url else None
            if avatar_path is not None:
                review["avatarRef"] = str(avatar_path)
            # 评论图像：真实格式 images[] 独立数组 + images/<sha1>.<ext> 平铺（已含子目录）。
            # 每个源图片占一个槽位（保序）：已缓存→本地路径；未缓存→空占位，绝不丢位。
            image_refs: list[str] = []
            images_orig: list[str] = []
            for img in images_urls:
                if not isinstance(img, dict):
                    image_refs.append("")
                    images_orig.append("")
                    continue
                url = str(img.get("url") or "").strip()
                if not url:
                    image_refs.append("")
                    images_orig.append("")
                    continue
                images_orig.append(url)
                media_path = _cached_media_path(folder, url)
                image_refs.append(str(media_path) if media_path is not None else "")
            if image_refs:
                review["imageRefs"] = image_refs
            if images_orig:
                review["imageSrcs"] = images_orig
            reviews.append(review)

        if not reviews and not total_count:
            continue
        paragraphs[str(paragraph_id)] = reviews
        total_comment_count += total_count or len(reviews)
        hot.append({
            "paragraphId": paragraph_id,
            "paragraphText": snippet,
            "matchedText": snippet,
            "matchedParagraphIndex": paragraph_id,
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



def _parse_chapter_url(url: str) -> tuple[str, str]:
    """chapterUrl: .../book_id/ch_id  → (book_id, ch_id)"""
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]


def _pending_chapter(chapter_url: str, msg: str, *, retryable: bool = False) -> dict:
    debug: dict[str, Any] = {"error": msg}
    if retryable:
        # 聚合器据此把"官方源下载中"判为可重试（LONG_RETRY_SCAN），而非死空。
        debug["retryable"] = True
    return {
        "sourceId": "fanqie_local",
        "chapterUrl": chapter_url,
        "title": "",
        "content": "",
        "format": "text",
        "debug": debug,
    }


async def _preview(ctx, book_id: str) -> dict:
    """调用 /api/preview/:book_id，缓存 _STATUS_CACHE_TTL 秒。"""
    cache_key = f"fanqie_preview:{book_id}"
    cached = ctx.cache_get(cache_key)
    if cached:
        return cached
    # 必须远低于 scheduler 的 detail 硬超时（默认 20s）：预览卡住会把整回调
    # 取消、book detail 返回 data=None → 404。收紧为短超时，失败即落到本地
    # status.json 快速回填（边下边读），不阻塞读路径。
    data = await ctx.access.http.fetch_json(
        f"{TOMATO_BASE}/api/preview/{book_id}",
        headers=_headers(),
        timeout=8,
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
        timeout=8,
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
