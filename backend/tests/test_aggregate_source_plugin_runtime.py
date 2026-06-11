"""Tests for aggregate source compatibility with plugin runtime."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_aggregate_source_endpoint():
    res = client.get("/api/legado/source")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 1
    source = data[0]
    assert "ruleSearch" in source
    assert "exploreUrl" in source
    assert "ruleExplore" in source
    assert "ruleBookInfo" in source
    assert "ruleToc" in source
    assert "ruleContent" in source


def test_search_via_api():
    res = client.get("/api/legado/search?keyword=test&waitMs=1")
    assert res.status_code == 200
    data = res.json()
    assert data["implemented"] is True
    assert "items" in data
    assert "debug" in data


def test_legado_search_returns_progressive_job_snapshot(monkeypatch):
    class FakeJob:
        job_id = "job-1"
        keyword = "剑宗外门"
        page = 1
        status = "running"
        candidate_groups = [
            {
                "candidateId": "book-1",
                "name": "剑宗外门",
                "author": "作者甲",
                "items": [{"name": "剑宗外门", "author": "作者甲", "sourceId": "fixture"}],
            }
        ]
        sources = [{"sourceId": "fixture"}]
        events = []

    class FakeSearchService:
        def find_active_job(self, keyword, page):
            return FakeJob()

        def cached_snapshot(self, keyword, page, base_api=None, include_official_sources=True):
            return None

        def snapshot(self, job, base_api=None, include_official_sources=True):
            return {
                "implemented": True,
                "keyword": job.keyword,
                "page": job.page,
                "jobId": job.job_id,
                "status": job.status,
                "items": job.candidate_groups[0]["items"],
                "candidateGroups": job.candidate_groups,
                "debug": {"partial": True, "sourceCount": 1},
            }

    import app.api.legado as legado_api

    monkeypatch.setattr(legado_api, "_get_search_service", lambda: FakeSearchService())

    res = client.get("/api/legado/search?keyword=剑宗外门&page=1&waitMs=1")

    assert res.status_code == 200
    data = res.json()
    assert data["jobId"] == "job-1"
    assert data["debug"]["partial"] is True
    assert data["items"][0]["name"] == "剑宗外门"


def test_legado_search_returns_cached_snapshot_and_starts_background_refresh(monkeypatch):
    class FakeJob:
        job_id = "job-cache-refresh"
        keyword = "剑宗外门"
        page = 1
        status = "running"
        candidate_groups = []
        sources = [{"sourceId": "fixture"}]
        events = []

    class FakeSearchService:
        def __init__(self):
            self.created_jobs = []
            self.persisted = []

        def cached_snapshot(self, keyword, page, base_api=None, include_official_sources=True):
            return {
                "implemented": True,
                "keyword": keyword,
                "page": page,
                "jobId": "",
                "status": "cached",
                "items": [{
                    "sourceId": "fixture",
                    "sourceName": "缓存书源",
                    "name": keyword,
                    "author": "作者甲",
                    "bookUrl": f"{base_api}/api/legado/book/fixture:abc",
                }],
                "candidateGroups": [],
                "debug": {"cacheHit": True},
            }

        def find_active_job(self, keyword, page):
            return None

        def create_job(self, keyword, page):
            job = FakeJob()
            self.created_jobs.append((keyword, page))
            return job

        def persist_job(self, job):
            self.persisted.append(job.job_id)

        def snapshot(self, job, base_api=None):
            raise AssertionError("cached path should return before snapshot()")

    import app.api.legado as legado_api

    fake_service = FakeSearchService()
    monkeypatch.setattr(legado_api, "_get_search_service", lambda: fake_service)
    monkeypatch.setattr(legado_api.threading, "Thread", lambda *args, **kwargs: type("T", (), {"start": lambda self: None})())

    res = client.get("/api/legado/search?keyword=剑宗外门&page=1&waitMs=1")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "cached"
    assert data["jobId"] == "job-cache-refresh"
    assert data["debug"]["cacheHit"] is True
    assert data["debug"]["backgroundRefresh"] is True
    assert fake_service.created_jobs == [("剑宗外门", 1)]


def test_legado_search_hides_official_sources_but_web_snapshot_can_keep_them(monkeypatch):
    class FakeJob:
        job_id = "job-official-hidden"
        keyword = "凡人修仙传"
        page = 1
        status = "completed"
        candidate_groups = []
        sources = [{"sourceId": "official_a"}, {"sourceId": "normal_b"}]
        events = []

    class FakeSearchService:
        def find_active_job(self, keyword, page):
            return FakeJob()

        def cached_snapshot(self, keyword, page, base_api=None, include_official_sources=True):
            items = [
                {"sourceId": "official_a", "sourceName": "起点中文网", "name": keyword, "author": "忘语", "bookUrl": f"{base_api}/api/legado/book/official"},
                {"sourceId": "normal_b", "sourceName": "普通源", "name": keyword, "author": "忘语", "bookUrl": f"{base_api}/api/legado/book/normal"},
            ]
            if not include_official_sources:
                items = [item for item in items if item["sourceId"] != "official_a"]
            return {
                "implemented": True,
                "keyword": keyword,
                "page": page,
                "jobId": "",
                "status": "cached",
                "items": items,
                "candidateGroups": [],
                "debug": {
                    "cacheHit": True,
                    "officialSourcesHidden": not include_official_sources,
                    "officialSourcesMatched": ["official_a"],
                    "officialSourcesMatchCount": 1,
                },
            }

        def snapshot(self, job, base_api=None, include_official_sources=True):
            items = [
                {"sourceId": "official_a", "sourceName": "起点中文网", "name": job.keyword, "author": "忘语", "bookUrl": f"{base_api}/api/legado/book/official"},
                {"sourceId": "normal_b", "sourceName": "普通源", "name": job.keyword, "author": "忘语", "bookUrl": f"{base_api}/api/legado/book/normal"},
            ]
            if not include_official_sources:
                items = [item for item in items if item["sourceId"] != "official_a"]
            return {
                "implemented": True,
                "keyword": job.keyword,
                "page": job.page,
                "jobId": job.job_id,
                "status": job.status,
                "items": items,
                "candidateGroups": [],
                "debug": {
                    "partial": False,
                    "officialSourcesHidden": not include_official_sources,
                    "officialSourcesMatched": ["official_a"],
                    "officialSourcesMatchCount": 1,
                },
            }

    import app.api.legado as legado_api

    monkeypatch.setattr(legado_api, "_get_search_service", lambda: FakeSearchService())

    legado_res = client.get("/api/legado/search?keyword=凡人修仙传&page=1&waitMs=1")

    assert legado_res.status_code == 200
    legado_data = legado_res.json()
    legado_items = legado_data["items"]
    assert [item["sourceId"] for item in legado_items] == ["normal_b"]
    assert legado_data["debug"]["officialSourcesHidden"] is True
    assert legado_data["debug"]["officialSourcesMatched"] == ["official_a"]
    assert legado_data["debug"]["officialSourcesMatchCount"] == 1

    service = FakeSearchService()
    web_snapshot = service.snapshot(FakeJob(), base_api="http://127.0.0.1:8765", include_official_sources=True)
    assert {item["sourceId"] for item in web_snapshot["items"]} == {"official_a", "normal_b"}
    assert web_snapshot["debug"]["officialSourcesHidden"] is False
    assert web_snapshot["debug"]["officialSourcesMatched"] == ["official_a"]
    assert web_snapshot["debug"]["officialSourcesMatchCount"] == 1


def test_search_service_snapshot_reports_official_source_debug(monkeypatch):
    from app.services.search_jobs import SearchJobService, SearchJob

    class FakeScheduler:
        def __init__(self):
            self._plugins = {
                "official_a": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: True})()})(),
                "normal_b": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: False})()})(),
            }

    service = SearchJobService()
    service.scheduler = FakeScheduler()

    job = SearchJob(
        job_id="job-official-debug",
        keyword="凡人修仙传",
        page=1,
        status="completed",
        created_at=0,
        sources=[{"sourceId": "official_a"}, {"sourceId": "normal_b"}],
        candidate_groups=[],
    )
    job.result = {
        "items": [
            {"sourceId": "official_a", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://a/book"},
            {"sourceId": "normal_b", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://b/book"},
        ]
    }

    legado_snap = service.snapshot(job, include_official_sources=False)
    assert legado_snap["debug"]["officialSourcesHidden"] is True
    assert legado_snap["debug"]["officialSourcesMatched"] == ["official_a"]
    assert legado_snap["debug"]["officialSourcesMatchCount"] == 1

    web_snap = service.snapshot(job, include_official_sources=True)
    assert web_snap["debug"]["officialSourcesHidden"] is False
    assert web_snap["debug"]["officialSourcesMatched"] == ["official_a"]
    assert web_snap["debug"]["officialSourcesMatchCount"] == 1

    service._cache.set_search("凡人修仙传", 1, {
        "items": [
            {"sourceId": "official_a", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://a/book"},
            {"sourceId": "normal_b", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://b/book"},
        ],
        "candidateGroups": [],
        "debug": {},
    })
    cached_legado = service.cached_snapshot("凡人修仙传", 1, include_official_sources=False)
    assert cached_legado["debug"]["officialSourcesHidden"] is True
    assert cached_legado["debug"]["officialSourcesMatched"] == ["official_a"]
    assert cached_legado["debug"]["officialSourcesMatchCount"] == 1

    cached_web = service.cached_snapshot("凡人修仙传", 1, include_official_sources=True)
    assert cached_web["debug"]["officialSourcesHidden"] is False
    assert cached_web["debug"]["officialSourcesMatched"] == ["official_a"]
    assert cached_web["debug"]["officialSourcesMatchCount"] == 1


def test_explore_via_api():
    res = client.get("/api/legado/explore?page=1")
    assert res.status_code == 200
    data = res.json()
    assert data["implemented"] is True
    assert "items" in data
    assert "debug" in data


def test_legado_explore_reports_browser_required_without_challenge(monkeypatch):
    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def explore_groups(self, source_id=None):
            return {
                "implemented": True,
                "groups": [{"sourceId": "fixture_cf", "groupId": "rank", "title": "排行榜"}],
                "debug": {},
            }

        async def explore(self, source_id, group_id=None, page=1):
            err = {
                "sourceId": source_id,
                "stage": "explore",
                "code": "BROWSER_REQUIRED",
                "message": "browser bypass required",
                "extra": {"bypassRequired": True},
            }
            return {
                "implemented": True,
                "sourceId": source_id,
                "groupId": group_id or "",
                "page": page,
                "items": [],
                "debug": {"error": err, "errors": [err]},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    res = client.get("/api/legado/explore?sourceId=fixture_cf&page=1")

    assert res.status_code == 200
    data = res.json()
    assert data["debug"]["error"]["code"] == "BROWSER_REQUIRED"
    assert data["debug"]["error"]["extra"]["bypassRequired"] is True
    assert "browserChallenges" not in data["debug"]


def test_legado_detail_reports_browser_required_without_challenge(monkeypatch):
    from app.source_plugins.id_codec import encode_book_id

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def detail(self, source_id, book_url):
            err = {
                "sourceId": source_id,
                "stage": "detail",
                "code": "BROWSER_REQUIRED",
                "message": "browser bypass required",
                "extra": {"bypassRequired": True},
            }
            return {"implemented": True, "data": None, "debug": {"error": err}}

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    book_id = encode_book_id("fixture_cf_detail", "https://example.com/book/1")
    res = client.get(f"/api/legado/book/{book_id}")

    assert res.status_code == 200
    data = res.json()
    assert data["data"] is None
    assert data["debug"]["error"]["code"] == "BROWSER_REQUIRED"
    assert data["debug"]["error"]["extra"]["bypassRequired"] is True
    assert "browserChallenges" not in data["debug"]


def test_legado_aggregate_detail_proxies_primary_source(monkeypatch):
    from app.services.aggregate_virtual_source import VIRTUAL_SOURCE_ID, make_aggregate_book_url
    from app.source_plugins.id_codec import encode_book_id

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def detail(self, source_id, book_url):
            return {
                "implemented": True,
                "data": {
                    "sourceId": source_id,
                    "name": "聚合样例",
                    "author": "作者甲",
                    "bookUrl": book_url,
                    "tocUrl": book_url,
                    "intro": "原始简介",
                    "lastChapter": "第二章",
                },
                "debug": {},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    group = {
        "candidateId": "candidate-1",
        "name": "聚合样例",
        "author": "作者甲",
        "items": [
            {
                "sourceId": "source_a",
                "sourceName": "Source A",
                "name": "聚合样例",
                "author": "作者甲",
                "bookUrl": "https://a.example/book/1",
                "score": 10,
            },
            {
                "sourceId": "source_b",
                "sourceName": "Source B",
                "name": "聚合样例",
                "author": "作者甲",
                "bookUrl": "https://b.example/book/1",
                "score": 20,
            },
        ],
    }
    book_id = encode_book_id(VIRTUAL_SOURCE_ID, make_aggregate_book_url(group))

    res = client.get(f"/api/legado/book/{book_id}")

    assert res.status_code == 200
    data = res.json()
    assert data["data"]["sourceId"] == VIRTUAL_SOURCE_ID
    assert data["data"]["sourceName"] == "LegadoHub AI聚合"
    assert data["data"]["name"] == "聚合样例"
    assert data["debug"]["aggregate"] is True
    assert data["debug"]["primaryBookId"].startswith("source_b:")
    assert data["debug"]["workflow"] == "ai_aggregate_purify"


def test_legado_aggregate_toc_uses_virtual_chapter_urls_and_placeholder(monkeypatch, tmp_path):
    import json
    import sqlite3
    import app.config as config
    import app.services.aggregate_processor as aggregate_processor
    from app.services.aggregate_virtual_source import VIRTUAL_SOURCE_ID, make_aggregate_book_url
    from app.source_plugins.id_codec import decode_chapter_id, encode_book_id
    from app.storage.db import initialize_database

    db_path = tmp_path / "aggregate.db"
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value_json) VALUES (?, ?)",
            (
                "contentWorkflow",
                json.dumps({"aiEnabled": True, "autoAggregate": True, "processAggregateOnRead": True}, ensure_ascii=False),
            ),
        )
        conn.commit()
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(aggregate_processor, "DB_PATH", db_path, raising=False)

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def detail(self, source_id, book_url):
            return {
                "implemented": True,
                "data": {
                    "sourceId": source_id,
                    "name": "聚合样例",
                    "author": "作者甲",
                    "bookUrl": book_url,
                    "tocUrl": book_url,
                },
                "debug": {},
            }

        async def toc(self, source_id, book_url):
            return {
                "implemented": True,
                "bookId": "",
                "chapters": [{"sourceId": source_id, "index": 1, "title": "第一章", "chapterUrl": "https://a.example/1.html"}],
                "debug": {},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    group = {
        "candidateId": "candidate-1",
        "name": "聚合样例",
        "author": "作者甲",
        "items": [
            {
                "sourceId": "source_a",
                "sourceName": "Source A",
                "name": "聚合样例",
                "author": "作者甲",
                "bookUrl": "https://a.example/book/1",
                "score": 10,
            }
        ],
    }
    book_id = encode_book_id(VIRTUAL_SOURCE_ID, make_aggregate_book_url(group))

    toc_res = client.get(f"/api/legado/book/{book_id}/toc")

    assert toc_res.status_code == 200
    chapter_url = toc_res.json()["chapters"][0]["chapterUrl"]
    assert "/api/legado/chapter/legadohub_ai_aggregate:" in chapter_url
    chapter_id = chapter_url.rsplit("/", 1)[-1]
    source_id, _ = decode_chapter_id(chapter_id)
    assert source_id == VIRTUAL_SOURCE_ID

    chapter_res = client.get(f"/api/legado/chapter/{chapter_id}")

    assert chapter_res.status_code == 200
    data = chapter_res.json()
    assert data["content"] == "正在聚合处理……请稍后刷新。"
    assert data["debug"]["aggregate"] is True


def test_legado_toc_reports_browser_required_without_challenge(monkeypatch):
    from app.source_plugins.id_codec import encode_book_id

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def toc(self, source_id, toc_url):
            err = {
                "sourceId": source_id,
                "stage": "toc",
                "code": "BROWSER_REQUIRED",
                "message": "browser bypass required",
                "extra": {"bypassRequired": True},
            }
            return {
                "implemented": True,
                "bookId": "",
                "chapters": [],
                "debug": {"error": err},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    book_id = encode_book_id("fixture_cf_toc", "https://example.com/book/2")
    res = client.get(f"/api/legado/book/{book_id}/toc")

    assert res.status_code == 200
    data = res.json()
    assert data["chapters"] == []
    assert data["debug"]["error"]["code"] == "BROWSER_REQUIRED"
    assert data["debug"]["error"]["extra"]["bypassRequired"] is True
    assert "browserChallenges" not in data["debug"]


def test_legado_chapter_reports_browser_required_without_challenge(monkeypatch):
    from app.source_plugins.id_codec import encode_chapter_id

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def chapter(self, source_id, chapter_url):
            err = {
                "sourceId": source_id,
                "stage": "chapter",
                "code": "BROWSER_REQUIRED",
                "message": "browser bypass required",
                "extra": {"bypassRequired": True},
            }
            return {
                "implemented": True,
                "chapterId": "",
                "title": "",
                "content": "",
                "debug": {"error": err},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    chapter_id = encode_chapter_id("fixture_cf_chapter", "https://example.com/chapter/1")
    res = client.get(f"/api/legado/chapter/{chapter_id}")

    assert res.status_code == 200
    data = res.json()
    assert data["content"] == ""
    assert data["debug"]["error"]["code"] == "BROWSER_REQUIRED"
    assert data["debug"]["error"]["extra"]["bypassRequired"] is True
    assert "browserChallenges" not in data["debug"]


def test_aggregate_source_generation():
    from app.core.source_generator import write_aggregate_source
    path = write_aggregate_source()
    assert path
    import json, pathlib
    p = pathlib.Path(path)
    assert p.exists()
    content = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(content, list)
    assert len(content) == 1
    assert content[0]["enabledExplore"] is False
    assert "ruleExplore" in content[0]
    assert "waitMs=180000" in content[0]["searchUrl"]


def test_legado_search_reading_fields_keep_book_metadata_and_source_display(monkeypatch):
    from app.services.search_jobs import SearchJob, SearchJobService

    service = SearchJobService()
    job = SearchJob(
        job_id="job-display",
        keyword="苟在两界修仙",
        page=1,
        status="running",
        created_at=0,
        sources=[{"sourceId": "fixture"}],
        candidate_groups=[
            {
                "candidateId": "book-1",
                "name": "苟在两界修仙",
                "author": "文抄公",
                "items": [
                    {
                        "sourceId": "fixture",
                        "sourceName": "101看书网",
                        "name": "苟在两界修仙",
                        "author": "文抄公",
                        "bookUrl": "https://101.example/book/1",
                        "kind": "仙侠 / 连载",
                        "lastChapter": "第524章 对比",
                        "wordCount": "163万字",
                    }
                ],
            }
        ],
    )

    snapshot = service.snapshot(job, base_api="http://192.168.31.189:8765")
    item = snapshot["items"][0]

    assert item["name"] == "苟在两界修仙"
    assert item["author"] == "文抄公"
    assert item["kind"] == "仙侠,连载"
    assert item["wordCount"] == "163万字"
    assert item["lastChapter"] == "第524章 对比"
    assert item["readingLastChapter"] == "101看书网 · 第524章 对比"
    assert item["bookUrl"].startswith("http://192.168.31.189:8765/api/legado/book/")


def test_legado_search_snapshot_uses_request_base_url_and_cache(monkeypatch):
    class FakeSearchService:
        def find_active_job(self, keyword, page):
            return type("FakeJob", (), {
                "job_id": "job-cache",
                "keyword": keyword,
                "page": page,
                "status": "completed",
                "candidate_groups": [],
                "sources": [],
                "completed_count": 0,
                "success_count": 0,
                "error_count": 0,
                "timeout_count": 0,
                "elapsed_ms": 0,
                "result": {
                    "items": [
                        {
                            "sourceId": "fixture",
                            "sourceName": "台灣小說網",
                            "name": keyword,
                            "author": "作者甲",
                            "bookUrl": "https://example.com/book/1",
                            "kind": "玄幻,连载",
                            "lastChapter": "第10章",
                            "cacheHit": True,
                            "cacheReason": "timeout",
                        }
                    ]
                },
            })()

        def snapshot(self, job, base_api=None, include_official_sources=True):
            return {
                "implemented": True,
                "keyword": job.keyword,
                "page": job.page,
                "jobId": job.job_id,
                "status": job.status,
                "items": [
                    {
                        "sourceId": "fixture",
                        "sourceName": "台灣小說網",
                        "name": job.keyword,
                        "author": "作者甲",
                        "bookUrl": f"{base_api}/api/legado/book/fixture:abc",
                        "kind": "玄幻,连载",
                        "lastChapter": "第10章",
                        "readingLastChapter": "台灣小說網 · 第10章",
                        "cacheHit": True,
                        "cacheReason": "timeout",
                    }
                ],
                "candidateGroups": [],
                "debug": {"cacheHit": True},
            }

    import app.api.legado as legado_api

    monkeypatch.setattr(legado_api, "_get_search_service", lambda: FakeSearchService())
    lan_client = TestClient(app, base_url="http://192.168.31.189:8765")

    res = lan_client.get("/api/legado/search?keyword=剑宗外门&page=1&waitMs=180000")

    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["bookUrl"].startswith("http://192.168.31.189:8765/")
    assert "127.0.0.1" not in item["bookUrl"]
    assert item["cacheHit"] is True
    assert item["cacheReason"] == "timeout"


def test_legado_ordinary_source_explore_is_disabled(monkeypatch):
    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def explore_groups(self, source_id=None):
            return {"groups": [{"groupId": "all", "groupName": "全部"}]}

        async def explore(self, source_id, group_id, page):
            return {
                "implemented": True,
                "sourceId": source_id,
                "groupId": group_id or "",
                "page": page,
                "items": [],
                "debug": {
                    "error": {
                        "sourceId": source_id,
                        "stage": "explore",
                        "code": "EXPLORE_OFFICIAL_SOURCE_REQUIRED",
                        "message": "普通书源不提供排行榜/分类，聚合源排行榜后续仅使用正版书源。",
                    },
                    "errors": [],
                },
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    res = client.get("/api/legado/explore?sourceId=fixture_ordinary&page=1")

    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["debug"]["error"]["code"] == "EXPLORE_OFFICIAL_SOURCE_REQUIRED"








def test_legado_aggregate_detail_shows_official_source_debug(monkeypatch):
    from app.services.aggregate_virtual_source import VIRTUAL_SOURCE_ID, make_aggregate_book_url
    from app.source_plugins.id_codec import encode_book_id

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def detail(self, source_id, book_url):
            return {
                "implemented": True,
                "data": {
                    "sourceId": source_id,
                    "name": "聚合样例",
                    "author": "作者甲",
                    "bookUrl": book_url,
                    "tocUrl": book_url,
                    "intro": "原始简介",
                    "lastChapter": "第二章",
                },
                "debug": {},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)
    monkeypatch.setattr(
        "app.source_plugins.loader.PluginLoader.load_all",
        lambda self: {
            "official_a": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: True})()})(),
            "source_b": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: False})()})(),
        },
    )
    monkeypatch.setattr(
        "app.source_plugins.loader.PluginLoader.load_all",
        lambda self: {
            "official_a": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: True})()})(),
            "source_b": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: False})()})(),
        },
    )

    group = {
        "candidateId": "candidate-1",
        "name": "聚合样例",
        "author": "作者甲",
        "items": [
            {
                "sourceId": "official_a",
                "sourceName": "Official A",
                "name": "聚合样例",
                "author": "作者甲",
                "bookUrl": "https://a.example/book/1",
                "score": 10,
            },
            {
                "sourceId": "source_b",
                "sourceName": "Source B",
                "name": "聚合样例",
                "author": "作者甲",
                "bookUrl": "https://b.example/book/1",
                "score": 20,
            },
        ],
    }
    book_id = encode_book_id(VIRTUAL_SOURCE_ID, make_aggregate_book_url(group))

    res = client.get(f"/api/legado/book/{book_id}")

    assert res.status_code == 200
    data = res.json()
    assert data["debug"]["hasOfficialSource"] is True
    assert data["debug"]["officialSourceIds"] == ["official_a"]
    assert data["debug"]["primarySourceIsOfficial"] is True


def test_legado_aggregate_toc_shows_official_source_debug(monkeypatch, tmp_path):
    import json
    import sqlite3
    import app.config as config
    import app.services.aggregate_processor as aggregate_processor
    from app.services.aggregate_virtual_source import VIRTUAL_SOURCE_ID, make_aggregate_book_url
    from app.source_plugins.id_codec import encode_book_id
    from app.storage.db import initialize_database

    db_path = tmp_path / "aggregate_toc_debug.db"
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value_json) VALUES (?, ?)",
            (
                "contentWorkflow",
                json.dumps({"aiEnabled": True, "autoAggregate": True, "processAggregateOnRead": True}, ensure_ascii=False),
            ),
        )
        conn.commit()
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(aggregate_processor, "DB_PATH", db_path, raising=False)

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def detail(self, source_id, book_url):
            return {
                "implemented": True,
                "data": {
                    "sourceId": source_id,
                    "name": "聚合样例",
                    "author": "作者甲",
                    "bookUrl": book_url,
                    "tocUrl": book_url,
                },
                "debug": {},
            }

        async def toc(self, source_id, book_url):
            return {
                "implemented": True,
                "bookId": "",
                "chapters": [{"sourceId": source_id, "index": 1, "title": "第一章", "chapterUrl": "https://a.example/1.html"}],
                "debug": {},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)
    monkeypatch.setattr(
        "app.source_plugins.loader.PluginLoader.load_all",
        lambda self: {
            "official_a": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: True})()})(),
            "source_b": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: False})()})(),
        },
    )
    monkeypatch.setattr(
        "app.source_plugins.loader.PluginLoader.load_all",
        lambda self: {
            "official_a": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: True})()})(),
            "source_b": type("P", (), {"metadata": type("M", (), {"is_official_source": lambda self: False})()})(),
        },
    )

    group = {
        "candidateId": "candidate-1",
        "name": "聚合样例",
        "author": "作者甲",
        "items": [
            {
                "sourceId": "official_a",
                "sourceName": "Official A",
                "name": "聚合样例",
                "author": "作者甲",
                "bookUrl": "https://a.example/book/1",
                "score": 10,
            }
        ],
    }
    book_id = encode_book_id(VIRTUAL_SOURCE_ID, make_aggregate_book_url(group))

    toc_res = client.get(f"/api/legado/book/{book_id}/toc")

    assert toc_res.status_code == 200
    toc_data = toc_res.json()
    assert toc_data["debug"]["hasOfficialSource"] is True
    assert toc_data["debug"]["officialSourceIds"] == ["official_a"]
    assert toc_data["debug"]["primarySourceIsOfficial"] is True
