"""Qidian official source plugin.

Night phase scope:
- official-source auth hooks
- unauthenticated mobile-site search/detail/toc/chapter/explore
- pageContext-based extraction for stable public data
"""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import quote, urljoin


class Source:
    id = "qidian_com"
    name = "起点中文网"
    contract_version = "1.0"
    last_modified = "2026-06-11"
    base_url = "https://www.qidian.com"
    mobile_base_url = "https://m.qidian.com"

    async def auth_status(self, ctx):
        """Check Qidian login state from stored cookies.

        Strategy:
        1. Collect cookies from all qidian.com subdomains.
        2. Verify presence of key login markers (ywguid, ywkey, cmfuToken, etc.).
        3. Attempt a lightweight mobile-site page probe to confirm cookies work.
        """
        all_cookies: dict[str, str] = {}
        for domain in ("qidian.com", "www.qidian.com", "m.qidian.com"):
            jar = ctx.cookies.get(domain)
            if isinstance(jar, dict):
                all_cookies.update(jar)

        if not all_cookies:
            return {
                "sourceId": self.id,
                "authenticated": False,
                "accountName": "",
                "expiresAt": "",
                "message": "未检测到起点登录 Cookie",
                "requiredActions": ["manual_login"],
            }

        # Key login markers observed from Web login (passport.qidian.com / passport.yuewen.com)
        # Note: cmfuToken / usertoken are App-only; Web login gives ywguid + ywkey + ywopenid.
        login_markers = {
            "ywguid": "用户 GUID",
            "ywkey": "登录密钥",
            "ywopenid": "阅文 OpenID",
            "_csrfToken": "CSRF Token",
            "QDInfo": "设备信息",
        }
        found = {k: login_markers[k] for k in login_markers if all_cookies.get(k)}

        # Critical fields for Web login: ywguid + ywkey are the bare minimum.
        critical = ("ywguid", "ywkey")
        has_critical = any(all_cookies.get(k) for k in critical)

        if not has_critical:
            return {
                "sourceId": self.id,
                "authenticated": False,
                "accountName": "",
                "expiresAt": "",
                "message": "Cookie 不完整，缺少关键登录态字段（ywguid / ywkey）",
                "requiredActions": ["manual_login"],
            }

        # Lightweight probe: use cookies to fetch mobile homepage and see if
        # pageContext is returned (WAF/login-page would not give stable JSON).
        try:
            html = await ctx.access.http.fetch_text(
                f"{self.mobile_base_url}/",
                headers={"Referer": self.mobile_base_url},
            )
            page_data = self._page_data(html)
        except Exception as exc:
            return {
                "sourceId": self.id,
                "authenticated": False,
                "accountName": "",
                "expiresAt": "",
                "message": f"Cookie 存在但页面探测异常：{exc}",
                "requiredActions": ["check_auth_status"],
            }

        # If pageContext exists, cookies are at least accepted by the server.
        if page_data:
            # Try to extract nickname if mobile homepage exposes userInfo.
            user_info = page_data.get("userInfo") or {}
            nick = user_info.get("nickName") if isinstance(user_info, dict) else None
            if nick:
                return {
                    "sourceId": self.id,
                    "authenticated": True,
                    "accountName": str(nick),
                    "expiresAt": "",
                    "message": f"已登录：{nick}",
                    "requiredActions": [],
                }

            # Page works but no explicit user info surfaced yet.
            marker_names = ", ".join(found.keys())
            return {
                "sourceId": self.id,
                "authenticated": False,
                "accountName": "",
                "expiresAt": "",
                "message": f"Cookie 有效（{marker_names}），页面访问正常，建议刷新状态确认完整登录态",
                "requiredActions": ["check_auth_status"],
            }

        # No pageContext means either WAF or login page → cookies likely invalid.
        return {
            "sourceId": self.id,
            "authenticated": False,
            "accountName": "",
            "expiresAt": "",
            "message": "Cookie 存在但页面未返回有效数据，可能已失效",
            "requiredActions": ["manual_login"],
        }

    async def prepare_login(self, ctx):
        return {
            "sourceId": self.id,
            "mode": "manual_browser",
            "loginUrl": "https://passport.qidian.com/",
            "instructions": "在打开的浏览器中完成起点登录（会自动重定向到阅文登录页），然后回到官方源登录页刷新状态。",
            "cookieDomains": ["qidian.com", "www.qidian.com", "m.qidian.com", "yuewen.com", "ptlogin.qidian.com", "ptlogin.yuewen.com"],
        }

    async def after_login(self, ctx):
        return await self.auth_status(ctx)

    async def chapter_reviews(self, ctx, chapter_url: str) -> dict:
        """Fetch chapter reviews, preferring private implementation when available."""
        from app.services.official_auth.loader import private_plugin_loader
        private = private_plugin_loader.load(self.id)
        reviews_impl = private.get("reviews")

        if reviews_impl:
            try:
                result = await reviews_impl.chapter_reviews(ctx, chapter_url)
                # If private returned empty with a hard error, fallback to public
                if result.get("debug", {}).get("error"):
                    return await self._public_chapter_reviews(ctx, chapter_url)
                return result
            except Exception as exc:
                if ctx:
                    ctx.trace("qidian.reviews.private", url=chapter_url, message=f"error={exc}")
                return {
                    "paragraphs": {},
                    "chapterEnd": [],
                    "summary": {},
                    "debug": {"error": f"reviews private plugin error: {exc}"},
                }

        return await self._public_chapter_reviews(ctx, chapter_url)

    async def _public_chapter_reviews(self, ctx, chapter_url: str) -> dict:
        book_id, chapter_id = self._parse_chapter_identifiers(chapter_url)
        if not book_id or not chapter_id:
            return self._empty_reviews("invalid qidian chapter url", auth_mode="public")

        csrf_token = self._csrf_token_from_cookies(ctx)
        if not csrf_token:
            csrf_token = await self._bootstrap_csrf_token(ctx, chapter_url)
        if not csrf_token:
            return self._empty_reviews("missing _csrfToken cookie", auth_mode="public")

        auth_mode = self._review_auth_mode(ctx, csrf_token)
        headers = {"Referer": chapter_url or self.mobile_base_url}
        try:
            summary_response = await ctx.access.http.fetch_json(
                f"{self.mobile_base_url}/webcommon/chapterreview/reviewsummary4m",
                params={
                    "bookId": book_id,
                    "chapterId": chapter_id,
                    "_csrfToken": csrf_token,
                },
                headers=headers,
            )
        except Exception as exc:
            if ctx:
                ctx.trace("qidian.reviews.summary", url=chapter_url, message=f"error={exc}")
            return self._empty_reviews(
                f"reviewsummary4m failed: {exc}",
                auth_mode=auth_mode,
                bookId=book_id,
                chapterId=chapter_id,
            )

        summary_payload = summary_response.get("data") if isinstance(summary_response, dict) else {}
        summary_list = summary_payload.get("list") if isinstance(summary_payload, dict) else []
        if not isinstance(summary_list, list):
            summary_list = []

        paragraphs_with_reviews = [
            self._safe_int(item.get("paragraphId"))
            for item in summary_list
            if isinstance(item, dict)
            and self._safe_int(item.get("paragraphId")) is not None
            and self._safe_int(item.get("paragraphId")) >= 0
            and self._safe_int(item.get("reviewNum"), 0) > 0
        ]
        chapter_end_count = 0
        for item in summary_list:
            if not isinstance(item, dict):
                continue
            if self._safe_int(item.get("paragraphId")) == -1:
                chapter_end_count = self._safe_int(item.get("reviewNum"), 0)
                break

        fetched_paragraphs = paragraphs_with_reviews[:20]
        paragraphs: dict[str, list[dict[str, Any]]] = {}
        for paragraph_id in fetched_paragraphs:
            comments = await self._fetch_review_list(
                ctx=ctx,
                book_id=book_id,
                chapter_id=chapter_id,
                paragraph_id=paragraph_id,
                csrf_token=csrf_token,
                headers=headers,
            )
            if comments:
                paragraphs[str(paragraph_id)] = comments

        chapter_end = await self._fetch_review_list(
            ctx=ctx,
            book_id=book_id,
            chapter_id=chapter_id,
            paragraph_id=-1,
            csrf_token=csrf_token,
            headers=headers,
        )

        summary = {
            "totalParagraphs": len(paragraphs_with_reviews),
            "totalReviews": self._safe_int(summary_payload.get("total"), 0),
            "paragraphsWithReviews": paragraphs_with_reviews,
            "fetchedParagraphs": fetched_paragraphs,
            "chapterEndCount": chapter_end_count,
            "authMode": auth_mode,
        }
        debug: dict[str, Any] = {}
        if len(paragraphs_with_reviews) > len(fetched_paragraphs):
            debug["truncatedParagraphCount"] = len(paragraphs_with_reviews) - len(fetched_paragraphs)
        if chapter_end_count and not chapter_end:
            debug["chapterEndExpected"] = chapter_end_count

        result: dict[str, Any] = {
            "paragraphs": paragraphs,
            "chapterEnd": chapter_end,
            "summary": summary,
        }
        if debug:
            result["debug"] = debug
        return result

    async def _bootstrap_csrf_token(self, ctx, chapter_url: str) -> str:
        if not ctx or not hasattr(ctx, "access"):
            return ""
        bootstrap_urls = [url for url in [chapter_url, self.mobile_base_url] if url]
        for bootstrap_url in bootstrap_urls:
            try:
                await ctx.access.http.fetch_text(
                    bootstrap_url,
                    headers={"Referer": self.mobile_base_url},
                )
            except Exception:
                continue
            token = self._csrf_token_from_cookies(ctx)
            if token:
                return token
        return ""

    async def _fetch_review_list(
        self,
        ctx,
        book_id: int,
        chapter_id: int,
        paragraph_id: int,
        csrf_token: str,
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        if not ctx:
            return []
        try:
            response = await ctx.access.http.fetch_json(
                f"{self.mobile_base_url}/webcommon/chapterreview/reviewlist4m",
                params={
                    "bookId": book_id,
                    "chapterId": chapter_id,
                    "paragraphId": paragraph_id,
                    "page": 1,
                    "_csrfToken": csrf_token,
                },
                headers=headers,
            )
        except Exception as exc:
            ctx.trace(
                "qidian.reviews.list",
                url=headers.get("Referer", ""),
                message=f"paragraphId={paragraph_id} error={exc}",
            )
            return []

        data = response.get("data") if isinstance(response, dict) else {}
        items = data.get("list") if isinstance(data, dict) else []
        if not isinstance(items, list):
            return []
        return [self._normalize_review_item(item, paragraph_id) for item in items if isinstance(item, dict)]

    def _normalize_review_item(self, item: dict[str, Any], paragraph_id: int) -> dict[str, Any]:
        user_info = item.get("userInfo") if isinstance(item.get("userInfo"), dict) else {}
        review_id = (
            item.get("reviewId")
            or item.get("id")
            or item.get("commentId")
            or item.get("replyId")
            or ""
        )
        like_num = self._safe_int(
            item.get("likeAmount", item.get("likeNum", item.get("praiseNum", 0))),
            0,
        )
        reply_list = item.get("replyList") if isinstance(item.get("replyList"), list) else []
        reply_count = self._safe_int(item.get("replyCount", item.get("replyAmount", len(reply_list))), len(reply_list))
        normalized = {
            "id": str(review_id),
            "content": self._text(item.get("content", "")),
            "userName": self._text(
                item.get("userName")
                or item.get("nickName")
                or user_info.get("nickName")
                or item.get("authorName")
                or ""
            ),
            "likeNum": like_num,
            "replyCount": reply_count,
            "reviewTime": self._text(
                item.get("createTimeStr")
                or item.get("ctimeDesc")
                or item.get("reviewTime")
                or item.get("timeDesc")
                or ""
            ),
            "paragraphId": paragraph_id,
            "isTop": bool(item.get("isTop") or item.get("top")),
        }
        avatar = self._cover(
            user_info.get("avatar")
            or item.get("avatar")
            or item.get("headImg")
            or ""
        )
        if avatar:
            normalized["avatar"] = avatar
        return normalized

    def _parse_chapter_identifiers(self, chapter_url: str) -> tuple[int | None, int | None]:
        match = re.search(r"/chapter/(\d+)/(\d+)/?", chapter_url or "")
        if not match:
            return None, None
        try:
            return int(match.group(1)), int(match.group(2))
        except ValueError:
            return None, None

    def _csrf_token_from_cookies(self, ctx) -> str:
        if not ctx or not hasattr(ctx, "cookies"):
            return ""
        for domain in (
            "m.qidian.com",
            "qidian.com",
            "www.qidian.com",
            "yuewen.com",
            "ptlogin.qidian.com",
            "ptlogin.yuewen.com",
        ):
            try:
                token = ctx.cookies.get(domain, "_csrfToken")
            except Exception:
                continue
            if token:
                return str(token)
        return ""

    def _review_auth_mode(self, ctx, csrf_token: str) -> str:
        if not ctx or not hasattr(ctx, "cookies"):
            return "public" if csrf_token else "none"
        for domain in ("qidian.com", "m.qidian.com", "www.qidian.com", "yuewen.com"):
            try:
                jar = ctx.cookies.get(domain)
            except Exception:
                continue
            if isinstance(jar, dict) and (jar.get("ywguid") or jar.get("ywkey")):
                return "cookie"
        return "public" if csrf_token else "none"

    def _safe_int(self, value: Any, default: int | None = None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _empty_reviews(self, error: str, **debug: Any) -> dict:
        payload: dict[str, Any] = {
            "paragraphs": {},
            "chapterEnd": [],
            "summary": {
                "totalParagraphs": 0,
                "totalReviews": 0,
                "paragraphsWithReviews": [],
                "chapterEndCount": 0,
                "authMode": debug.get("auth_mode", "public"),
            },
        }
        debug_payload = {"error": error}
        debug_payload.update(debug)
        payload["debug"] = debug_payload
        return payload

    def _page_data(self, html: str) -> dict:
        match = re.search(
            r'<script id="vite-plugin-ssr_pageContext" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
        except Exception:
            return {}
        page_context = payload.get("pageContext") if isinstance(payload, dict) else {}
        page_props = page_context.get("pageProps") if isinstance(page_context, dict) else {}
        page_data = page_props.get("pageData") if isinstance(page_props, dict) else {}
        return page_data if isinstance(page_data, dict) else {}

    def _text(self, value: str) -> str:
        text = unescape(str(value or ""))
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</p>\s*<p>", "\n\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = "\n".join(line.strip() for line in text.splitlines())
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _cover(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("//"):
            return f"https:{url}"
        return url

    def _book_url(self, book_id: int | str) -> str:
        return f"{self.mobile_base_url}/book/{book_id}/"

    def _catalog_url(self, book_id: int | str) -> str:
        return f"{self.mobile_base_url}/book/{book_id}/catalog/"

    def _chapter_url(self, book_id: int | str, chapter_id: int | str) -> str:
        return f"{self.mobile_base_url}/chapter/{book_id}/{chapter_id}/"

    def _search_items_from_page_data(self, ctx, page_data: dict) -> list[dict]:
        records = (((page_data.get("bookInfo") or {}).get("records")) or [])
        items = []
        for record in records:
            if not isinstance(record, dict):
                continue
            book_id = record.get("bid", "")
            if not book_id:
                continue
            category = self._text(record.get("cat", ""))
            sub_category = self._text(record.get("subCateName", ""))
            state = self._text(record.get("state", ""))
            kind_parts = [part for part in [category, sub_category, state] if part]
            items.append({
                "sourceId": self.id,
                "name": self._text(record.get("bName", "")),
                "author": self._text(record.get("bAuth", "")),
                "bookUrl": self._book_url(book_id),
                "coverUrl": self._cover(record.get("imgUrl", "")),
                "intro": self._text(record.get("desc", "")),
                "kind": ",".join(kind_parts),
                "lastChapter": self._text(record.get("lastChapterName", "")),
                "wordCount": self._text(record.get("cnt", "")),
                "updateTime": self._text(record.get("lastUpdateTime", "") or record.get("updateTime", "")),
                "extra": {
                    "bookId": book_id,
                    "categoryId": record.get("catId", ""),
                    "subCategoryId": record.get("subCateId", ""),
                    "isVip": bool(record.get("isVip")),
                    "signStatus": self._text(record.get("signStatus", "")),
                },
            })
        return items

    def _book_detail_from_page_data(self, ctx, book_url: str, page_data: dict) -> dict:
        book_info = page_data.get("bookInfo") or {}
        book_extra = page_data.get("bookExtra") or {}
        book_id = book_info.get("bookId") or book_info.get("bid") or page_data.get("bookId") or ""
        sub_category = self._text(book_info.get("subCateName", ""))
        category = self._text(book_info.get("chanName", ""))
        state = self._text(book_info.get("bookStatus", "") or book_info.get("actionStatus", ""))
        kind_parts = [part for part in [category, sub_category, state] if part]
        tags = []
        for tag in (book_extra.get("ugcTagInfos") or []):
            if isinstance(tag, dict):
                name = self._text(tag.get("tagName", ""))
                if name:
                    tags.append(name)
        return {
            "sourceId": self.id,
            "name": self._text(book_info.get("bookName", "")),
            "author": self._text(book_info.get("authorName", "")),
            "bookUrl": book_url,
            "coverUrl": self._cover(book_info.get("coverUrl", "")),
            "intro": self._text(book_info.get("desc", "")),
            "kind": ",".join(kind_parts),
            "lastChapter": self._text(book_info.get("updChapterName", "")),
            "wordCount": self._text(book_info.get("showWordsCnt", "") or book_info.get("wordsCnt", "")),
            "updateTime": self._text(book_info.get("updTime", "")),
            "tocUrl": self._catalog_url(book_id) if book_id else book_url,
            "authRequired": False,
            "extra": {
                "bookId": book_id,
                "categoryId": book_info.get("chanId", ""),
                "subCategoryId": book_info.get("subCateId", ""),
                "latestChapterUrl": self._cover(book_info.get("updChapterUrl", "")),
                "limitFreeType": book_extra.get("limitFreeType", page_data.get("limitFreeType", 0)),
                "tags": tags,
                "rankName": self._text((book_extra.get("tagInfo") or {}).get("rankName", "")),
                "rankNum": self._text((book_extra.get("tagInfo") or {}).get("rankNum", "")),
                "bookCirclePostCount": book_extra.get("bookCirclePostCount", 0),
            },
        }

    def _toc_from_page_data(self, page_data: dict) -> list[dict]:
        volumes = page_data.get("vs") or []
        book_id = page_data.get("bookId", "")
        chapters = []
        for volume in volumes:
            volume_name = self._text(volume.get("vN", "")) if isinstance(volume, dict) else ""
            for chapter in (volume.get("cs") or []):
                if not isinstance(chapter, dict):
                    continue
                chapter_id = chapter.get("id", "")
                title = self._text(chapter.get("cN", ""))
                if not chapter_id or not title:
                    continue
                # sS: 1=free, 0=vip/paid (opposite of intuitive bool)
                is_vip = not bool(chapter.get("sS", 1))
                chapters.append({
                    "sourceId": self.id,
                    "index": len(chapters) + 1,
                    "title": title,
                    "chapterUrl": self._chapter_url(book_id, chapter_id),
                    "updateTime": self._text(chapter.get("uT", "")),
                    "isVip": is_vip,
                    "isLocked": False,
                    "extra": {
                        "volumeName": volume_name,
                        "wordCount": chapter.get("cnt", 0),
                        "vipFlag": chapter.get("sS", 0),
                    },
                })
        return chapters

    def _chapter_from_page_data(self, ctx, chapter_url: str, page_data: dict) -> dict:
        chapter_info = page_data.get("chapterInfo") or {}
        content = self._text(chapter_info.get("content", ""))
        is_buy = bool(chapter_info.get("isBuy", 0))
        price = int(chapter_info.get("price", 0) or 0)
        vip_status = int(chapter_info.get("vipStatus", 0) or 0)
        return {
            "sourceId": self.id,
            "title": self._text(chapter_info.get("chapterName", "")),
            "content": content,
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": (not is_buy) and not bool(content),
            "isPaid": bool(price > 0 or vip_status),
            "extra": {
                "chapterId": chapter_info.get("chapterId", ""),
                "bookId": (page_data.get("bookInfo") or {}).get("bookId", ""),
                "isBuy": is_buy,
                "price": price,
                "vipStatus": vip_status,
                "freeStatus": chapter_info.get("freeStatus", 0),
                "limitFree": chapter_info.get("limitFree", 0),
                "wordsCount": chapter_info.get("wordsCount", 0),
                "previewOnly": (not is_buy) and bool(content),
            },
        }

    async def search(self, ctx, keyword: str, page: int):
        url = f"{self.mobile_base_url}/soushu/{quote(keyword)}.html"
        if page > 1:
            url += f"?pageNum={page}"
        html = await ctx.access.http.fetch_text(url, headers={"Referer": self.mobile_base_url})
        page_data = self._page_data(html)
        ctx.trace("qidian.search.mobile", url=url, message=f"records={len(((page_data.get('bookInfo') or {}).get('records')) or [])}")
        return self._search_items_from_page_data(ctx, page_data)

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url, headers={"Referer": self.mobile_base_url})
        page_data = self._page_data(html)
        ctx.trace("qidian.detail.mobile", url=book_url, message=f"bookId={(page_data.get('bookInfo') or {}).get('bookId', '')}")
        return self._book_detail_from_page_data(ctx, book_url, page_data)

    async def toc(self, ctx, toc_url: str):
        html = await ctx.access.http.fetch_text(toc_url, headers={"Referer": self.mobile_base_url})
        page_data = self._page_data(html)
        chapters = self._toc_from_page_data(page_data)
        ctx.trace("qidian.toc.mobile", url=toc_url, message=f"chapters={len(chapters)}")
        return chapters

    async def chapter(self, ctx, chapter_url: str):
        html = await ctx.access.http.fetch_text(chapter_url, headers={"Referer": self.mobile_base_url})
        page_data = self._page_data(html)
        result = self._chapter_from_page_data(ctx, chapter_url, page_data)
        ctx.trace("qidian.chapter.mobile", url=chapter_url, message=f"contentLength={len(result.get('content', ''))}")
        return result

    async def explore_groups(self, ctx):
        groups = [
            {"sourceId": self.id, "groupId": "rank_yuepiao", "title": "男生月票榜", "url": f"{self.mobile_base_url}/rank/yuepiao/", "kind": "rank", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "rank_hotsales", "title": "男生畅销榜", "url": f"{self.mobile_base_url}/rank/hotsales/", "kind": "rank", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "rank_readindex", "title": "男生阅读榜", "url": f"{self.mobile_base_url}/rank/readindex/", "kind": "rank", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "rank_recom", "title": "男生推荐榜", "url": f"{self.mobile_base_url}/rank/recom/", "kind": "rank", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "rank_update", "title": "男生更新榜", "url": f"{self.mobile_base_url}/rank/update/", "kind": "rank", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "rank_sign", "title": "男生签约榜", "url": f"{self.mobile_base_url}/rank/sign/", "kind": "rank", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "rank_newbook", "title": "男生新书榜", "url": f"{self.mobile_base_url}/rank/newbook/", "kind": "rank", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "cat_xuanhuan", "title": "分类·玄幻", "url": f"{self.mobile_base_url}/category/catid21/", "kind": "category", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "cat_xianxia", "title": "分类·仙侠", "url": f"{self.mobile_base_url}/category/catid22/", "kind": "category", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "cat_dushi", "title": "分类·都市", "url": f"{self.mobile_base_url}/category/catid4/", "kind": "category", "pageable": True, "extra": {}},
            {"sourceId": self.id, "groupId": "cat_kehuan", "title": "分类·科幻", "url": f"{self.mobile_base_url}/category/catid9/", "kind": "category", "pageable": True, "extra": {}},
        ]
        ctx.trace("qidian.explore_groups.mobile", message=f"groups={len(groups)}")
        return groups

    def _explore_items_from_html(self, ctx, base_url: str, html: str) -> list[dict]:
        soup = ctx._to_lxml(html)
        items = []
        seen = set()
        for a in soup.cssselect("a[data-bid]"):
            href = a.get("href", "")
            bid = a.get("data-bid", "")
            if not bid or bid in seen:
                continue
            seen.add(bid)
            title = ctx.clean_text(" ".join(a.cssselect("h2")[0].itertext())) if a.cssselect("h2") else ""
            cover = ""
            img_nodes = a.cssselect("img")
            if img_nodes:
                cover = img_nodes[0].get("data-src") or img_nodes[0].get("src") or ""
            desc = ""
            author = ""
            kind = ""
            word_count = ""
            desc_nodes = a.cssselect("p._searchBookDesc_1lmme_521")
            if desc_nodes:
                desc = ctx.clean_text(" ".join(desc_nodes[0].itertext()))
            author_nodes = a.cssselect("p._searchBookAuthor_1lmme_613")
            if author_nodes:
                author = ctx.clean_text(" ".join(author_nodes[0].itertext()))
            if not author:
                sub_title_nodes = a.cssselect("p._subTitle_17ayl_725")
                if sub_title_nodes:
                    parts = [ctx.clean_text(part) for part in sub_title_nodes[0].text_content().split("·") if ctx.clean_text(part)]
                    if parts:
                        author = parts[0]
                    if len(parts) >= 2:
                        kind = parts[1]
                    if len(parts) >= 3:
                        word_count = parts[2]
            tag_nodes = a.cssselect("div._tags_1lmme_700 p")
            if tag_nodes:
                tags = [ctx.clean_text(node.text_content()) for node in tag_nodes if ctx.clean_text(node.text_content())]
                if len(tags) >= 2:
                    kind = ",".join(tags[:-1])
                    word_count = tags[-1]
                elif tags:
                    kind = ",".join(tags)
            items.append({
                "sourceId": self.id,
                "sourceName": self.name,
                "name": title,
                "author": author,
                "bookUrl": self._book_url(bid),
                "coverUrl": self._cover(cover),
                "intro": desc,
                "kind": kind,
                "lastChapter": "",
                "wordCount": word_count,
                "extra": {"bookId": bid, "rawHref": urljoin(base_url, href)},
            })
        return items

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        groups = await self.explore_groups(ctx)
        target = next((group for group in groups if group["groupId"] == (group_id or "")), groups[0] if groups else None)
        if not target:
            return []
        url = target["url"]
        if page > 1:
            url = f"{url.rstrip('/')}/page{page}/"
        html = await ctx.access.http.fetch_text(url, headers={"Referer": self.mobile_base_url})
        items = self._explore_items_from_html(ctx, url, html)
        ctx.trace("qidian.explore.mobile", url=url, message=f"group={target['groupId']} items={len(items)}")
        return items
