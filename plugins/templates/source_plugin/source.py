"""Template source plugin."""


class Source:
    id = "example_com"
    name = "示例书源"
    contract_version = "1.0"
    base_url = "https://example.com"

    async def search(self, ctx, keyword: str, page: int):
        html = await ctx.fetch_text(f"{self.base_url}/search")
        ctx.trace("parse", message="TODO: implement search parser")
        return []

    async def detail(self, ctx, book_url: str):
        html = await ctx.fetch_text(book_url)
        ctx.trace("parse", message="TODO: implement detail parser")
        return {"sourceId": self.id, "bookUrl": book_url, "tocUrl": book_url}

    async def toc(self, ctx, toc_url: str):
        html = await ctx.fetch_text(toc_url)
        ctx.trace("parse", message="TODO: implement toc parser")
        return []

    async def chapter(self, ctx, chapter_url: str):
        html = await ctx.fetch_text(chapter_url)
        ctx.trace("parse", message="TODO: implement chapter parser")
        return {"sourceId": self.id, "chapterUrl": chapter_url, "title": "", "content": ""}
