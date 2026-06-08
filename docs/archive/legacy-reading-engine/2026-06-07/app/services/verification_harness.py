"""Verification harness for real API and UI smoke assertions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT


REPORT_PATH = PROJECT_ROOT / "docs" / "verification" / "verification-report.json"


class VerificationHarness:
    """Run deterministic smoke checks and record real pass/fail outcomes."""

    def __init__(self):
        self.results: list[dict] = []

    def record(self, category: str, name: str, passed: bool, details: str = "") -> None:
        self.results.append({
            "category": category,
            "name": name,
            "passed": passed,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def check(self, category: str, name: str, assertion: Callable[[], str | None]) -> None:
        try:
            details = assertion()
            self.record(category, name, True, details or "断言通过")
        except Exception as exc:
            self.record(category, name, False, str(exc))

    def get_report(self) -> dict:
        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "summary": {"passed": passed, "failed": total - passed, "total": total},
            "items": self.results,
        }

    def save_report(self) -> str:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(self.get_report(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(REPORT_PATH)

    def run_api_simulations(self) -> dict:
        """Run API smoke checks against the in-process FastAPI app."""
        self.results = []

        from app.main import app

        with TestClient(app) as client:
            self.check("api", "settings_get", lambda: self._expect_json_keys(
                client.get("/api/admin/settings"),
                ["sourcePool", "ruleEngines", "sourceSubscriptions"],
            ))
            self.check("api", "source_subscriptions_list", lambda: self._expect_items_response(
                client.get("/api/admin/source-subscriptions"),
            ))
            self.check("api", "sources_list", lambda: self._expect_json_keys(
                client.get("/api/admin/sources?limit=1"),
                ["items", "stats"],
            ))
            self.check("api", "search_job_create", lambda: self._expect_json_keys(
                client.post("/api/admin/search-jobs", json={"keyword": "verification-smoke", "page": 1, "limit": 0}),
                ["jobId", "status", "keyword"],
            ))
            self.check("api", "search_stream", lambda: self._expect_status(
                client.get("/api/admin/search/stream?keyword=verification-smoke&limit=0"),
                200,
                "text/event-stream",
            ))
            self.check("api", "explore_sources", lambda: self._expect_items_response(
                client.get("/api/admin/explore/sources"),
            ))
            self.check("api", "books_list", lambda: self._expect_items_response(
                client.get("/api/admin/books?limit=1"),
            ))
            self.check("api", "chapter_navigation", lambda: self._expect_json_keys(
                client.get("/api/admin/books/fake/chapters/fake-chapter/navigation"),
                ["prev", "next"],
            ))
            self.check("api", "cache_status", lambda: self._expect_json_keys(
                client.get("/api/admin/cache"),
                ["searchCache", "bookCache", "tocCache", "chapterCache"],
            ))
            self.check("api", "progress_status", lambda: self._expect_json_keys(
                client.get("/api/admin/progress"),
                ["aggregate", "sources"],
            ))
            self.check("api", "rule_engine_capabilities", lambda: self._expect_rule_engine_capabilities(
                client.get("/api/admin/rule-engines"),
            ))

        return self.get_report()

    def run_ui_simulations(self) -> dict:
        """Run UI route smoke checks for rendered Chinese admin pages."""
        if not self.results:
            self.results = []

        from app.main import app

        pages = [
            ("/admin", "仪表盘"),
            ("/admin/source-subscriptions", "订阅源管理"),
            ("/admin/sources", "书源管理"),
            ("/admin/search", "搜索工作台"),
            ("/admin/explore", "发现 / 排行榜"),
            ("/admin/books", "书籍记录"),
            ("/admin/reader", "阅读器"),
            ("/admin/update-tasks", "追更任务"),
            ("/admin/cache", "缓存管理"),
            ("/admin/settings", "设置"),
            ("/admin/rule-engines", "规则引擎"),
            ("/admin/rule-audit", "规则引擎审查"),
            ("/admin/aggregate-source", "聚合书源"),
            ("/admin/verification", "验证中心"),
        ]

        with TestClient(app) as client:
            for path, text in pages:
                self.check("ui", path, lambda path=path, text=text: self._expect_html_text(client.get(path), text))

        return self.get_report()

    def load_last_report(self) -> dict:
        if REPORT_PATH.exists():
            return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        return self.get_report()

    def _expect_status(self, response, status: int, content_type_prefix: str = "") -> str:
        if response.status_code != status:
            raise AssertionError(f"状态码 {response.status_code}，预期 {status}")
        if content_type_prefix:
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith(content_type_prefix):
                raise AssertionError(f"Content-Type {content_type}，预期以 {content_type_prefix} 开头")
        return f"HTTP {response.status_code}"

    def _expect_json_keys(self, response, keys: list[str]) -> str:
        self._expect_status(response, 200)
        data = response.json()
        missing = [key for key in keys if key not in data]
        if missing:
            raise AssertionError(f"缺少字段: {', '.join(missing)}")
        return f"字段存在: {', '.join(keys)}"

    def _expect_items_response(self, response) -> str:
        self._expect_json_keys(response, ["items"])
        data = response.json()
        if not isinstance(data.get("items"), list):
            raise AssertionError("items 不是数组")
        return f"items={len(data['items'])}"

    def _expect_html_text(self, response, expected_text: str) -> str:
        self._expect_status(response, 200)
        normalized = response.text.replace(" ", "")
        if expected_text not in response.text and expected_text.replace(" ", "") not in normalized:
            raise AssertionError(f"页面缺少文本: {expected_text}")
        if "<button" not in response.text and "<form" not in response.text and "href=" not in response.text:
            raise AssertionError("页面缺少可交互控件或导航")
        return f"页面包含: {expected_text}"

    def _expect_rule_engine_capabilities(self, response) -> str:
        self._expect_json_keys(response, ["items"])
        data = response.json()
        legado = next((item for item in data["items"] if item.get("id") == "legado"), None)
        if not legado:
            raise AssertionError("缺少 legado 引擎")
        capabilities = {item.get("id"): item for item in legado.get("capabilities", [])}
        required = ["css_selector", "xpath", "jsonpath", "regex", "pagination", "webview"]
        missing = [item for item in required if item not in capabilities]
        if missing:
            raise AssertionError(f"缺少能力项: {', '.join(missing)}")
        return f"capabilities={len(capabilities)}"
