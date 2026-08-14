from __future__ import annotations

import asyncio
import importlib.util
import io
import zipfile
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
            "coverUrl": "https://example.test/cover.heic",
            "intro": "软件测试理论与实践相结合。",
            "kind": "教育/教材/计算机",
            "lastChapter": "第9章 测试文档",
            "wordCount": "12万字",
            "extra": {"book_id": "7156171587174009864"},
        }
    ]


def _epub_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf">'
            '<manifest><item id="intro" href="aux_00000.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="toc" href="table-of-contents.html" media-type="application/xhtml+xml"/>'
            '<item id="c1" href="chapter_00001.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="c2" href="chapter_00002.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="r2" href="aux_00003.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="avatar" href="images/avatar.jpg" media-type="image/jpeg"/></manifest>'
            '<spine><itemref idref="intro"/><itemref idref="toc"/><itemref idref="c1"/>'
            '<itemref idref="c2"/><itemref idref="r2"/></spine></package>',
        )
        archive.writestr("OEBPS/aux_00000.xhtml", "<html><body><h1>简介</h1><p>书籍介绍。</p></body></html>")
        archive.writestr("OEBPS/table-of-contents.html", "<html><body><h1>目录</h1></body></html>")
        archive.writestr(
            "OEBPS/chapter_00001.xhtml",
            '<html><body><h1>第一章 开始</h1><p id="p-0">第一章正文。</p></body></html>',
        )
        archive.writestr(
            "OEBPS/chapter_00002.xhtml",
            '<html><body><h1>第二章 继续</h1><p id="p-0">第二章正文。<a class="seg-count" href="aux_00003.xhtml#para-0">(1)</a></p></body></html>',
        )
        archive.writestr(
            "OEBPS/aux_00003.xhtml",
            '<html><body><h2>第二章 继续 - 段评</h2><h3 id="para-0">'
            '<span class="para-src">&quot;第二章正文。&quot;</span></h3><ol>'
            '<li class="seg-item"><p>写得很好。</p><p><small class="seg-meta">'
            '<img class="avatar" src="images/avatar.jpg"/>作者：测试读者 | 时间：1720000000 | 赞：12'
            '</small></p></li></ol></body></html>',
        )
        archive.writestr("OEBPS/images/avatar.jpg", b"\xff\xd8\xff\xe0fake-jpeg")
    return output.getvalue()


class _DownloadedHttp:
    def __init__(self, save_dir: Path) -> None:
        self.root_scans = 0
        self.status_calls = 0
        self.save_dir = save_dir

    async def fetch_json(self, url: str, **kwargs):
        if url.endswith("/api/status"):
            self.status_calls += 1
            return {
                "version": "2.4.13",
                "save_dir": str(self.save_dir),
                "locked": False,
                "config": {"use_official_api": True},
            }
        if url.endswith("/api/jobs"):
            return {
                "items": [{
                    "id": 7,
                    "book_id": "7156171587174009864",
                    "title": "软件测试",
                    "state": "done",
                    "updated_ms": 2000,
                }]
            }
        if url.endswith("/api/library"):
            self.root_scans += 1
            if self.root_scans == 1:
                return {"items": [], "running": True, "error": None}
            return {
                "items": [{
                    "kind": "file",
                    "name": "软件测试.epub",
                    "rel_path": "软件测试.epub",
                    "ext": "epub",
                    "modified_ms": 2000,
                }],
                "running": False,
                "error": None,
            }
        raise AssertionError(url)

    async def fetch_bytes(self, url: str, **kwargs):
        raise AssertionError("EPUB must be read from status.save_dir, not /download")


class _DownloadedContext(_Context):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__()
        self.save_dir = tmp_path
        (self.save_dir / "软件测试.epub").write_bytes(_epub_bytes())
        self.access = type("Access", (), {"http": _DownloadedHttp(self.save_dir)})()
        self.cache: dict[str, object] = {}

    def cache_get(self, key: str):
        return self.cache.get(key)

    def cache_set(self, key: str, value, ttl_seconds: int = 300) -> None:
        self.cache[key] = value

    @staticmethod
    def decode_text(content: bytes, charset: str | None = None) -> str:
        return content.decode(charset or "utf-8")


def test_toc_reads_completed_epub_after_library_scan_finishes(tmp_path: Path) -> None:
    ctx = _DownloadedContext(tmp_path)
    source = Source()
    book_url = f"{MODULE.TOMATO_BASE}/__fanqie__/7156171587174009864"

    chapters = asyncio.run(source.toc(ctx, book_url))
    chapter = asyncio.run(source.chapter(ctx, chapters[1]["chapterUrl"]))

    assert [item["title"] for item in chapters] == ["第一章 开始", "第二章 继续"]
    assert chapter["title"] == "第二章 继续"
    assert chapter["content"] == "第二章正文。"
    assert ctx.access.http.root_scans >= 2
    assert ctx.access.http.status_calls == 1
    assert not hasattr(ctx.access.http, "downloads")


def test_chapter_reviews_reads_tomato_segment_comment_page(tmp_path: Path) -> None:
    ctx = _DownloadedContext(tmp_path)
    source = Source()
    chapter_url = f"{MODULE.TOMATO_BASE}/__fanqie__/7156171587174009864/2"

    reviews = asyncio.run(source.chapter_reviews(ctx, chapter_url))

    assert reviews["paragraphs"]["0"][0] == {
        "id": "fanqie-local-2-0-1",
        "content": "写得很好。",
        "userName": "测试读者",
        "likeNum": 12,
        "reviewTime": "2024-07-03 09:46:40",
        "paragraphId": 0,
        "avatarRef": "OEBPS/images/avatar.jpg",
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
