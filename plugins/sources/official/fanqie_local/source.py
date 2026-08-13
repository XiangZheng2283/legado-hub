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
import os
import re
import time
from typing import Any

TOMATO_BASE = os.environ.get("FANQIE_LOCAL_BASE", "http://127.0.0.1:18423").rstrip("/")
TOMATO_PASSWD = os.environ.get("FANQIE_LOCAL_PASSWD", "")
DOWNLOAD_TIMEOUT_S = int(os.environ.get("FANQIE_LOCAL_TIMEOUT", "900"))
_POLL_S = 5
_STATUS_CACHE_TTL = 60
_ORDER_CACHE_TTL = 300


class Source:
    id = "fanqie_local"
    name = "番茄小说（本地下载器）"
    contract_version = "1.0"
    last_modified = "2026-08-13"

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
                "coverUrl": _pick_string(
                    raw,
                    "detail_page_thumb_url",
                    "detail_thumb_url",
                    "thumb_url",
                    "cover_url",
                    "audio_thumb_url_hd",
                    "audio_thumb_uri",
                ),
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
            "coverUrl": _cover_url(book_id),
            "intro": str(data.get("description") or ""),
            "kind": "/".join(kind_parts),
            "lastChapter": str(data.get("last_chapter_title") or ""),
            "wordCount": word_count_str,
            "tocUrl": book_url,
            "extra": {"book_id": book_id},
        }

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        """
        目录顺序来自 /download/<book_id>/status.json 中 downloaded 的写入顺序，
        但 status.json 不经过 library API 暴露。我们改用已落盘的 txt 文件解析章节标题序列；
        若 txt 尚未下载，则触发下载后再解析。
        """
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
        """
        等整本 txt 下载完毕后，从文件中按章节 index 截取内容返回。
        """
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

        # 从全文 txt 缓存里取该章节内容
        rel_path = await _find_txt_rel(ctx, book_id)
        if not rel_path:
            return _pending_chapter(chapter_url, "下载文件未找到，请稍后重试。")

        full_text = await self._get_full_text(ctx, rel_path)
        if not full_text:
            return _pending_chapter(chapter_url, "读取文件失败，请稍后重试。")

        chapters = _split_txt(full_text)
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

    # ── 内部辅助 ──────────────────────────────────────────────────

    async def _chapter_order(self, ctx, book_id: str) -> list[tuple[str, str]]:
        """
        返回 [(chapter_fake_id, title), ...] 的有序列表。
        chapter_fake_id 是按顺序生成的数字字符串（1-based），因为 txt 本身没有原始 ID。
        若 txt 不存在则触发下载并等待完成。
        结果缓存 _ORDER_CACHE_TTL 秒。
        """
        cache_key = f"fanqie_order:{book_id}"
        cached = ctx.cache_get(cache_key)
        if cached:
            return cached

        rel_path = await _find_txt_rel(ctx, book_id)
        if not rel_path:
            rel_path = await self._ensure_downloaded(ctx, book_id)
        if not rel_path:
            return []

        full_text = await self._get_full_text(ctx, rel_path)
        if not full_text:
            return []

        chapters = _split_txt(full_text)
        order = [(str(i + 1), title) for i, (title, _content) in enumerate(chapters)]
        ctx.cache_set(cache_key, order, _ORDER_CACHE_TTL)
        return order

    async def _get_full_text(self, ctx, rel_path: str) -> str:
        """下载 txt 全文，缓存 _ORDER_CACHE_TTL 秒。"""
        cache_key = f"fanqie_txt:{rel_path}"
        cached = ctx.cache_get(cache_key)
        if cached is not None:
            return cached
        try:
            raw = await ctx.access.http.fetch_bytes(
                f"{TOMATO_BASE}/download/{rel_path}",
                headers=_headers(),
                timeout=60,
            )
            text = ctx.decode_text(raw)
        except Exception as e:
            ctx.trace("chapter", message=f"fetch txt failed: {e}")
            return ""
        ctx.cache_set(cache_key, text, _ORDER_CACHE_TTL)
        return text

    async def _ensure_downloaded(self, ctx, book_id: str) -> str | None:
        """
        触发下载 job，轮询等待 Done，自动回应 book_name/format 选择，
        返回 txt rel_path 或 None。
        """
        # 先看有没有已完成的 job
        existing = await _find_done_job(ctx, book_id)
        if existing:
            return await _find_txt_rel(ctx, book_id)

        # 创建新 job
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

        job_id = resp.get("id")
        if not job_id:
            # 已有活跃任务（下载器限制同时只允许 1 个），等它完成
            job_id = await _wait_for_active_job(ctx, book_id)
            if not job_id:
                return None

        # 轮询等待完成
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
                break
            job = items[0]
            state = job.get("state", "")

            # 自动回应书名 / 格式选择（保持默认即可）
            if job.get("book_name_options"):
                await _submit_choice(ctx, job_id, "book_name", None)
            if job.get("format_options"):
                await _submit_choice(ctx, job_id, "format", None)

            if state == "done":
                break
            if state in ("failed", "canceled"):
                ctx.trace("chapter", message=f"job {job_id} ended with state={state}: {job.get('message')}")
                return None

        return await _find_txt_rel(ctx, book_id)


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


def _parse_chapter_url(url: str) -> tuple[str, str]:
    """chapterUrl: .../book_id/ch_id  → (book_id, ch_id)"""
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]


def _pending_chapter(chapter_url: str, msg: str) -> dict:
    return {
        "sourceId": "fanqie_local",
        "chapterUrl": chapter_url,
        "title": "",
        "content": msg,
        "format": "text",
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


async def _find_txt_rel(ctx, book_id: str) -> str | None:
    """
    在 library 里找 book_id 目录下的 txt 文件，返回 rel_path。
    目录名就是 book_id（safe_fs_name 对纯数字不做修改）。
    """
    try:
        root = await ctx.access.http.fetch_json(
            f"{TOMATO_BASE}/api/library",
            params={"start": "false"},
            headers=_headers(),
            timeout=10,
        )
    except Exception:
        return None

    target_dir = None
    for item in root.get("items") or []:
        if item.get("kind") == "dir" and item.get("name", "") == book_id:
            target_dir = item.get("rel_path", "")
            break
    if target_dir is None:
        return None

    try:
        sub = await ctx.access.http.fetch_json(
            f"{TOMATO_BASE}/api/library",
            params={"path": target_dir, "start": "false"},
            headers=_headers(),
            timeout=10,
        )
    except Exception:
        return None

    for item in sub.get("items") or []:
        if item.get("kind") == "file" and item.get("ext") == "txt":
            return item.get("rel_path", "")
    return None


async def _find_done_job(ctx, book_id: str) -> int | None:
    """返回该 book_id 最近一个 done 状态的 job id，否则 None。"""
    try:
        data = await ctx.access.http.fetch_json(
            f"{TOMATO_BASE}/api/jobs",
            params={"all": "true"},
            headers=_headers(),
            timeout=10,
        )
    except Exception:
        return None
    for job in data.get("items") or []:
        if str(job.get("book_id", "")) == book_id and job.get("state") == "done":
            return job.get("id")
    return None


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
