from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "sources"
    / "official"
    / "fanqie_local"
    / "source.py"
)
SPEC = importlib.util.spec_from_file_location("test_fanqie_local_source", SOURCE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
Source = MODULE.Source


class _Http:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def fetch_json(self, url: str, **kwargs):
        self.urls.append(url)
        if url.endswith("/api/search"):
            return {
                "items": [
                    {
                        "book_id": "7156171587174009864",
                        "title": "软件测试",
                        "author": "黑马程序员",
                        "raw": {
                            "abstract": "软件测试理论与实践相结合。",
                            "audio_thumb_url_hd": "https://example.test/cover.heic",
                            "word_count": "123456",
                            "category_name": "教育",
                            "last_chapter_title": "第9章 测试文档",
                            "book_tags": ["教材", "计算机"],
                        },
                    }
                ]
            }
        raise AssertionError(f"search must not call the preview endpoint: {url}")


class _Context:
    def __init__(self) -> None:
        self.access = type("Access", (), {"http": _Http()})()
        self.traces: list[dict] = []

    def trace(self, stage: str, **payload) -> None:
        self.traces.append({"stage": stage, **payload})

    @staticmethod
    def cache_get(key: str):
        return None

    @staticmethod
    def cache_set(key: str, value, ttl_seconds: int = 300) -> None:
        return None


def test_search_maps_raw_metadata_without_preview_requests() -> None:
    ctx = _Context()

    items = asyncio.run(Source().search(ctx, "test", 1))

    assert ctx.access.http.urls == [f"{MODULE.TOMATO_BASE}/api/search"]
    assert items == [
        {
            "sourceId": "fanqie_local",
            "name": "软件测试",
            "author": "黑马程序员",
            "bookUrl": f"{MODULE.TOMATO_BASE}/__fanqie__/7156171587174009864",
            "coverUrl": "",
            "intro": "软件测试理论与实践相结合。",
            "kind": "教育/教材/计算机",
            "lastChapter": "第9章 测试文档",
            "wordCount": "12万字",
            "extra": {"book_id": "7156171587174009864"},
        }
    ]




def test_toc_reads_incremental_journal(tmp_path: Path) -> None:
    MODULE._PROC_CACHE.clear()
    book = "7156171587174009864"
    folder = tmp_path / book
    _write_journal(folder, [
        {"id": "fnq-100", "title": "第一章 开始", "content": "<p>第一章正文。</p>"},
        {"id": "fnq-200", "title": "第二章 继续", "content": "<p>第二章正文。</p>"},
    ])
    ctx = _JobContext(tmp_path, [])
    source = Source()
    book_url = f"{MODULE.TOMATO_BASE}/__fanqie__/{book}"

    chapters = asyncio.run(source.toc(ctx, book_url))
    chapter_url = chapters[1]["chapterUrl"]
    chapter = asyncio.run(source.chapter(ctx, chapter_url))

    assert [item["title"] for item in chapters] == ["第一章 开始", "第二章 继续"]
    assert chapter["title"] == "第二章 继续"
    assert chapter["content"] == "第二章正文。"
    # 命中即不打 /api/jobs：下载完的书每次读都在增量落盘上直取
    assert ctx.http.job_url_calls == 0


def test_toc_empty_triggers_job(tmp_path: Path) -> None:
    MODULE._PROC_CACHE.clear()
    book = "777"
    folder = tmp_path / book
    folder.mkdir(parents=True, exist_ok=True)  # 空目录：尚未下载/journal 为空
    ctx = _JobContext(tmp_path, [])
    src = Source()
    toc_url = f"{MODULE.TOMATO_BASE}/__fanqie__/{book}"

    got = asyncio.run(src.toc(ctx, toc_url))

    assert got == []
    # 空目录必须触发下载 job，否则目录永远空、用户点不进章节（死锁）
    assert ctx.http.posts == [book]


def test_chapter_reviews_reads_segment_comments_json(tmp_path: Path) -> None:
    MODULE._PROC_CACHE.clear()
    import hashlib as _hashlib
    book = "7156171587174009864"
    folder = tmp_path / book
    _write_journal(folder, [
        {"id": "fnq-100", "title": "第一章 开始", "content": "<p>第一章正文。</p>"},
        {"id": "fnq-200", "title": "第二章 继续", "content": "<p>第二章正文。</p>"},
    ])
    avatar_url = "https://example.test/avatar.jpg"
    sha = _hashlib.sha1(avatar_url.encode("utf-8")).hexdigest()
    (folder / "images").mkdir()
    (folder / "images" / f"{sha}.jpg").write_bytes(b"\xff\xd8\xef\xbf\xbd")
    seg = {
        "chapter_id": "fnq-200",
        "book_id": book,
        "item_version": 1,
        "top_n": 0,
        "paras": {
            "0": {
                "count": 1,
                "detail": {
                    "meta": {"para_content": "第二章正文。"},
                    "reviews": [{
                        "user": {"name": "测试读者", "avatar": avatar_url},
                        "text": "写得很好。",
                        "created_ts": 1720000000,
                        "digg_count": 12,
                        "images": [],
                    }],
                },
            }
        },
    }
    (folder / "segment_comments").mkdir()
    (folder / "segment_comments" / "fnq-200.json").write_text(
        _json.dumps(seg, ensure_ascii=False), encoding="utf-8"
    )

    ctx = _JobContext(tmp_path, [])
    source = Source()
    chapter_url = f"{MODULE.TOMATO_BASE}/__fanqie__/{book}/2"

    reviews = asyncio.run(source.chapter_reviews(ctx, chapter_url))

    # 约定：人物头像视为不存在，不给 avatarRef（头像不加载、当没有）。
    assert reviews["paragraphs"]["0"][0] == {
        "id": "fanqie-local-2-0-1",
        "content": "写得很好。",
        "userName": "测试读者",
        "likeNum": 12,
        "reviewTime": "2024-07-03 09:46:40",
        "paragraphId": 0,
    }
    assert reviews["hotParagraphReviews"] == [{
        "paragraphId": 0,
        "paragraphText": "第二章正文。",
        "matchedText": "第二章正文。",
        "matchedParagraphIndex": 0,
        "matchedParagraphCount": 1,
        "matchStatus": "direct",
        "matchConfidence": 1.0,
        "commentCount": 1,
        "hotCommentCount": 1,
        "totalCommentCount": 1,
        "topReviews": [reviews["paragraphs"]["0"][0]],
    }]
    assert reviews["summary"] == {
        "totalParagraphs": 1,
        "totalReviews": 1,
        "paragraphsWithReviews": [0],
        "paragraphStats": {"0": 1},
        "embeddedReviews": 1,
        "totalCommentCount": 1,
        "chapterEndCount": 0,
        "hotParagraphCount": 1,
    }
# ── P2：job 触发幂等 / 429 降级 / 先读后触发 ─────────────────────────────
import json as _json


class _JobHttp:
    """可控的 /api/status + /api/jobs mock，用于 P2 幂等 / 429 / 先读后触发。"""

    def __init__(self, save_dir: Path, jobs=None, create_error=None) -> None:
        self.save_dir = save_dir
        self.jobs = list(jobs or [])
        self.create_error = create_error
        self.posts: list[str] = []
        self.job_url_calls = 0

    async def fetch_json(self, url: str, **kwargs):
        if url.endswith("/api/status"):
            return {
                "version": "2.4.13",
                "save_dir": str(self.save_dir),
                "locked": False,
                "config": {"use_official_api": True},
            }
        if url.endswith("/api/jobs"):
            self.job_url_calls += 1
            if str(kwargs.get("method", "GET")).upper() == "POST":
                if self.create_error is not None:
                    raise self.create_error
                book_id = str((kwargs.get("json") or {}).get("book_id"))
                self.posts.append(book_id)
                jid = 9000 + len(self.posts)
                self.jobs.append({"id": jid, "book_id": book_id, "state": "queued", "title": "", "updated_ms": 0})
                return {"id": jid}
            return {"items": self.jobs}
        raise AssertionError(url)


class _JobContext(_Context):
    def __init__(self, save_dir: Path, jobs=None, create_error=None) -> None:
        super().__init__()
        self.save_dir = save_dir
        self.http = _JobHttp(save_dir, jobs=jobs, create_error=create_error)
        self.access = type("Access", (), {"http": self.http})()

    def cache_get(self, key: str):
        return None


def _write_journal(folder: Path, rows) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "downloaded_chapters.jsonl").write_text(
        "\n".join(_json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def test_ensure_job_started_reuses_running_without_post(tmp_path: Path) -> None:
    MODULE._PROC_CACHE.clear()
    book = "111"
    ctx = _JobContext(tmp_path, [{"id": 5, "book_id": book, "state": "running", "title": "x"}])
    out = asyncio.run(MODULE._ensure_job_started(ctx, book))
    assert out["disposition"] == "existing_running" and out["started"] is True and out["job_id"] == 5
    assert ctx.http.posts == []


def test_ensure_job_started_creates_when_absent(tmp_path: Path) -> None:
    MODULE._PROC_CACHE.clear()
    ctx = _JobContext(tmp_path, [])
    out = asyncio.run(MODULE._ensure_job_started(ctx, "222"))
    assert out["disposition"] == "created" and out["started"] is True
    assert ctx.http.posts == ["222"]


def test_ensure_job_started_throttled_on_429(tmp_path: Path) -> None:
    MODULE._PROC_CACHE.clear()
    ctx = _JobContext(tmp_path, [], create_error=RuntimeError("429 Too Many Requests"))
    out = asyncio.run(MODULE._ensure_job_started(ctx, "333"))
    assert out["disposition"] == "throttled" and out["started"] is False
    assert ctx.http.posts == []


def test_ensure_job_started_failed_not_recreated(tmp_path: Path) -> None:
    MODULE._PROC_CACHE.clear()
    book = "444"
    ctx = _JobContext(tmp_path, [{"id": 9, "book_id": book, "state": "failed", "title": "x"}])
    out = asyncio.run(MODULE._ensure_job_started(ctx, book))
    assert out["disposition"] == "existing_failed" and out["started"] is False
    assert ctx.http.posts == []


def test_chapter_hit_does_not_call_jobs(tmp_path: Path) -> None:
    MODULE._PROC_CACHE.clear()
    book = "555"
    folder = tmp_path / book
    _write_journal(folder, [{"id": "c1", "title": "第一章", "content": "<p>正文一</p>"}])
    ctx = _JobContext(tmp_path, [])
    src = Source()
    result = asyncio.run(src.chapter(ctx, f"{MODULE.TOMATO_BASE}/__fanqie__/{book}/1"))
    assert result["content"] == "正文一"
    assert ctx.http.job_url_calls == 0  # 命中不打 /api/jobs


def test_chapter_missing_triggers_job_and_retryable(tmp_path: Path) -> None:
    MODULE._PROC_CACHE.clear()
    book = "666"
    folder = tmp_path / book
    _write_journal(folder, [{"id": "c1", "title": "第一章", "content": "<p>正文一</p>"}])
    ctx = _JobContext(tmp_path, [])
    src = Source()
    # 请求第 5 章（未下）→ 触发 job + retryable pending
    result = asyncio.run(src.chapter(ctx, f"{MODULE.TOMATO_BASE}/__fanqie__/{book}/5"))
    assert result["content"] == "" and result["debug"].get("retryable") is True
    assert ctx.http.posts == [book]

