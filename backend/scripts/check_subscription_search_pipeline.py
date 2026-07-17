"""Self-checks for the shared subscription search pipeline."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.subscription_search import SubscriptionSearchService
from app.services.user_auth import UserAuthService
from app.storage.db import initialize_database


class FakeMetadata:
    def __init__(self, plugin_id: str, name: str, official: bool):
        self.id = plugin_id
        self.name = name
        self.enabled = True
        self.priority = 10
        self._official = official

    def is_official_source(self) -> bool:
        return self._official


class FakePlugin:
    def __init__(self, plugin_id: str, name: str, official: bool):
        self.metadata = FakeMetadata(plugin_id, name, official)
        self.capabilities = ["search"]


class FakeScheduler:
    def __init__(self, plugins: list[FakePlugin], results: dict[str, list[dict[str, Any]]]):
        self.plugins = plugins
        self.results = results
        self.config = {"max_concurrency": 3}

    def _enabled_plugins(self) -> list[FakePlugin]:
        return self.plugins

    def _search_priority_plugins(self, plugins: list[FakePlugin]) -> list[FakePlugin]:
        return sorted(
            plugins,
            key=lambda plugin: (
                0 if plugin.metadata.is_official_source() else 1,
                plugin.metadata.id,
            ),
        )

    async def search_one(self, plugin_id: str, keyword: str, page: int = 1) -> dict[str, Any]:
        return {"items": [dict(item) for item in self.results.get(plugin_id, [])], "error": None}

    def _source_result_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for item in items:
            copied = dict(item)
            copied.setdefault("rawBookUrl", copied.get("bookUrl", ""))
            copied.setdefault("bookId", f"{copied.get('sourceId', '')}:{copied.get('rawBookUrl', '')}")
            normalized.append(copied)
        return normalized


class FakeLibraryService:
    def build_subscription_card(self, group: dict[str, Any]) -> dict[str, Any]:
        items = [item for item in group.get("items", []) if isinstance(item, dict)]
        return {
            "candidateId": group.get("candidateId", ""),
            "name": group.get("name", ""),
            "author": group.get("author", ""),
            "sourceSummary": [
                {"sourceId": item.get("sourceId", ""), "sourceName": item.get("sourceName", "")}
                for item in items
            ],
            "sourceCount": len(items),
        }


class FakeSubscriptionService:
    def get(self, user_id: str, book_id: str) -> None:
        return None


async def run_job(
    service: SubscriptionSearchService,
    owner_user_id: str,
    keyword: str = "剑宗外门",
) -> dict[str, Any]:
    job = service.create_job(keyword, 1, owner_user_id=owner_user_id)
    while service.snapshot(job.job_id).get("liveSearchPending"):
        await asyncio.sleep(0.01)
    return service.snapshot(job.job_id)


async def main() -> None:
    official = FakePlugin("official-a", "官方源", True)
    third = FakePlugin("third-a", "第三方源", False)

    with TemporaryDirectory(prefix="legadohub-subscription-search-") as temp_dir:
        db_path = Path(temp_dir) / "app.db"
        initialize_database(db_path)
        auth = UserAuthService(db_path)
        owner = auth.create_user("self-check-owner", "self-check-password")
        other = auth.create_user("self-check-other", "self-check-password")
        scheduler = FakeScheduler(
            [official, third],
            {
                "official-a": [
                    {
                        "sourceId": "official-a",
                        "sourceName": "官方源",
                        "name": "剑宗外门",
                        "author": "乘风",
                        "bookUrl": "official://book-a",
                    }
                ]
            },
        )
        service = SubscriptionSearchService(
            scheduler=scheduler,
            library_service=FakeLibraryService(),
            subscription_service=FakeSubscriptionService(),
            db_path=db_path,
        )
        snapshot = await run_job(service, owner["userId"])
        assert snapshot["mode"] == "official-primary", snapshot
        assert len(snapshot["cards"]) == 1, snapshot
        assert snapshot["cards"][0]["name"] == "剑宗外门", snapshot
        assert snapshot["cards"][0]["sourceCount"] == 1, snapshot
        assert "cardGroups" not in snapshot and "card_groups" not in snapshot, snapshot
        source_ids = {
            source["sourceId"] for source in snapshot["cards"][0]["sourceSummary"]
        }
        assert source_ids == {"official-a"}, snapshot
        assert service.get_job_for_user(snapshot["jobId"], owner["userId"]) is not None
        assert service.get_job_for_user(snapshot["jobId"], other["userId"]) is None
        assert service.find_card_group(snapshot["jobId"], "not-current-card") is None

        reloaded = SubscriptionSearchService(
            scheduler=scheduler,
            library_service=FakeLibraryService(),
            subscription_service=FakeSubscriptionService(),
            db_path=db_path,
        )
        assert reloaded.snapshot(snapshot["jobId"])["cards"] == snapshot["cards"]
        candidate_id = snapshot["cards"][0]["candidateId"]
        assert reloaded.find_card_group_for_user(
            snapshot["jobId"], candidate_id, owner["userId"]
        ) is not None
        assert reloaded.find_card_group_for_user(
            snapshot["jobId"], candidate_id, other["userId"]
        ) is None

        no_official_service = SubscriptionSearchService(
            scheduler=FakeScheduler([third], {"third-a": []}),
            library_service=FakeLibraryService(),
            subscription_service=FakeSubscriptionService(),
            db_path=db_path,
        )
        no_official = await run_job(no_official_service, owner["userId"])
        assert no_official["mode"] == "no-official-source", no_official
        assert no_official["cards"] == [], no_official

    print("subscription search pipeline self-check passed")


if __name__ == "__main__":
    asyncio.run(main())
