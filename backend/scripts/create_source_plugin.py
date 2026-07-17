"""Create a formal LegadoHub source plugin scaffold."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import yaml


PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def validate_plugin_id(plugin_id: str) -> None:
    if not PLUGIN_ID_RE.match(plugin_id):
        raise ValueError("plugin id must match ^[a-z0-9][a-z0-9_]*$")
    if plugin_id.startswith("demo_"):
        raise ValueError("plugin id must not start with demo_")


def create_plugin(
    *,
    plugin_id: str,
    name: str,
    domain: str,
    base_url: str,
    output_root: Path,
    force: bool = False,
) -> Path:
    validate_plugin_id(plugin_id)
    plugin_dir = output_root / plugin_id
    if plugin_dir.exists():
        if not force:
            raise FileExistsError(f"plugin already exists: {plugin_dir}")
        shutil.rmtree(plugin_dir)

    fixture_dir = plugin_dir / "smoke" / "fixtures"
    fixture_dir.mkdir(parents=True)

    metadata = {
        "contractVersion": "1.0",
        "id": plugin_id,
        "name": name,
        "author": "Yunwei",
        "version": "0.1.0",
        "type": "source",
        "domains": [domain],
        "baseUrls": [base_url],
        "capabilities": ["search", "detail", "toc", "chapter"],
        "auth": {
            "mode": "none",
            "loginUrl": base_url,
            "accountRequiredFor": [],
            "cookieDomains": [domain],
        },
        "content": {"access": "unknown", "paid": "unknown"},
        "tags": ["html"],
        "enabled": True,
        "sourceSeed": {"type": "manual", "upstreamId": domain, "upstreamFile": "", "upstreamCommit": ""},
    }
    (plugin_dir / "metadata.yaml").write_text(yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (plugin_dir / "source.py").write_text(_source_template(plugin_id, name, base_url), encoding="utf-8")
    (plugin_dir / "README.md").write_text(_readme_template(plugin_id, name, domain, base_url), encoding="utf-8")
    (plugin_dir / "smoke" / "smoke.yaml").write_text(_smoke_template(base_url), encoding="utf-8")
    for fixture_name in ("search.html", "detail.html", "toc.html", "chapter.html"):
        (fixture_dir / fixture_name).write_text("<!-- Replace with captured fixture HTML. -->\n", encoding="utf-8")
    return plugin_dir


def _source_template(plugin_id: str, name: str, base_url: str) -> str:
    return f'''"""Source plugin for {name}."""


class Source:
    id = "{plugin_id}"
    name = "{name}"
    contract_version = "1.0"
    base_url = "{base_url.rstrip("/")}"

    async def search(self, ctx, keyword: str, page: int):
        html = await ctx.access.http.fetch_text(f"{{self.base_url}}/search")
        ctx.trace("parse", message="TODO: implement search parser")
        return []

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url)
        ctx.trace("parse", message="TODO: implement detail parser")
        return {{
            "sourceId": self.id,
            "name": ctx.text(html, "h1"),
            "author": ctx.text(html, ".author"),
            "bookUrl": book_url,
            "coverUrl": ctx.urljoin(book_url, ctx.attr(html, ".cover img", "src")),
            "intro": ctx.text(html, ".intro"),
            "kind": ctx.text(html, ".kind"),
            "lastChapter": ctx.text(html, ".latest"),
            "wordCount": ctx.text(html, ".word-count"),
            "tocUrl": book_url,
            "authRequired": False,
            "extra": {{
                "status": ctx.text(html, ".status"),
                "updateTime": ctx.text(html, ".update-time"),
            }},
        }}

    async def toc(self, ctx, toc_url: str):
        html = await ctx.access.http.fetch_text(toc_url)
        ctx.trace("parse", message="TODO: implement toc parser")
        return []

    async def chapter(self, ctx, chapter_url: str):
        html = await ctx.access.http.fetch_text(chapter_url)
        ctx.trace("parse", message="TODO: implement chapter parser")
        return {{"sourceId": self.id, "chapterUrl": chapter_url, "title": "", "content": ""}}
'''


def _smoke_template(base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"""keyword: 凡人修仙传
fixtures:
  search:
    url: {base}/search
    file: search.html
  detail:
    url: {base}/book/1/
    file: detail.html
  toc:
    url: {base}/book/1/
    file: toc.html
  chapter:
    url: {base}/book/1/1.html
    file: chapter.html
expect:
  search:
    minResults: 1
    firstName: 凡人修仙传
  detail:
    name: 凡人修仙传
    author: 忘语
    hasTocUrl: true
  toc:
    minChapters: 1
    firstTitleContains: 第
  chapter:
    minContentLength: 20
    titleContains: 第
"""


def _readme_template(plugin_id: str, name: str, domain: str, base_url: str) -> str:
    return f"""# {name}

- Plugin ID: `{plugin_id}`
- Domain: `{domain}`
- Base URL: `{base_url}`
- Auth: none
- Content: unknown

## Fixture Smoke

Replace `smoke/fixtures/*.html` with captured search/detail/toc/chapter pages, then run:

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/{plugin_id}
```

Detail output should fill Reading-compatible fields whenever the page exposes
them: `name`, `author`, `bookUrl`, `coverUrl`, `intro`, `kind`, `lastChapter`,
`wordCount`, `tocUrl`, `authRequired`, and useful extras such as `status` or
`updateTime`.

Ordinary mirror/scraper sources must not declare `explore`; ranking and category
capabilities are reserved for official/licensed sources.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a LegadoHub source plugin scaffold")
    parser.add_argument("--id", required=True, dest="plugin_id")
    parser.add_argument("--name", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-root", default="../plugins/sources")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        plugin_dir = create_plugin(
            plugin_id=args.plugin_id,
            name=args.name,
            domain=args.domain,
            base_url=args.base_url,
            output_root=Path(args.output_root).resolve(),
            force=args.force,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(plugin_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
