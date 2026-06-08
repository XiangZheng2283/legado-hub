"""Controlled headless browser fetch for source plugins."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT
from app.source_plugins.challenges import looks_like_any_challenge
from app.source_plugins.errors import BrowserRequired, FetchNetworkError, PluginTimeout


class BrowserFetchService:
    """Fetch a page through Playwright while runtime owns proxy and context."""

    def __init__(
        self,
        root_dir: Path | None = None,
        proxy_url: str = "",
        user_agent: str = "",
        cookies: dict[str, dict[str, str]] | None = None,
    ):
        self.root_dir = root_dir or PROJECT_ROOT
        self.backend_dir = self.root_dir / "backend"
        self.frontend_dir = self.root_dir / "frontend"
        self.output_dir = self.backend_dir / "data" / "browser_fetch"
        self.script_path = self.backend_dir / "scripts" / "browser_fetch_helper.mjs"
        self.proxy_url = proxy_url
        self.user_agent = user_agent
        self.cookies = cookies or {}
        self.last_cookies: list[dict[str, Any]] = []

    async def fetch_text(
        self,
        plugin_id: str,
        url: str,
        *,
        method: str = "GET",
        data: dict | None = None,
        timeout: float = 90.0,
        wait_ms: int = 2500,
    ) -> str:
        if not self.script_path.exists():
            raise BrowserRequired(f"browser fetch helper missing: {self.script_path}", url=url)
        if not (self.frontend_dir / "node_modules" / "playwright").exists():
            raise BrowserRequired("Playwright is not installed under frontend/node_modules", url=url)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        profile_dir = self.output_dir / f"{plugin_id}-{uuid.uuid4().hex[:12]}-profile"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=self.output_dir, encoding="utf-8") as tmp:
            out_file = Path(tmp.name)
        cookies_file: Path | None = None
        playwright_cookies = self._playwright_cookies()
        if playwright_cookies:
            with tempfile.NamedTemporaryFile("w", suffix=".cookies.json", delete=False, dir=self.output_dir, encoding="utf-8") as tmp:
                cookies_file = Path(tmp.name)
                tmp.write(json.dumps(playwright_cookies, ensure_ascii=False))

        cmd = [
            "node",
            str(self.script_path),
            "--url",
            url,
            "--out",
            str(out_file),
            "--user-data-dir",
            str(profile_dir),
            "--method",
            method,
            "--wait-ms",
            str(wait_ms),
        ]
        if data:
            cmd.extend(["--data-json", json.dumps(data, ensure_ascii=False)])
        if self.proxy_url:
            cmd.extend(["--proxy", self.proxy_url])
        if self.user_agent:
            cmd.extend(["--user-agent", self.user_agent])
        if cookies_file:
            cmd.extend(["--cookies-json", str(cookies_file)])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.frontend_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise BrowserRequired("node is required for browser fetch", url=url) from exc

        try:
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout + 8)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise PluginTimeout(f"browser fetch timeout: {url}") from exc
        except asyncio.CancelledError:
            process.kill()
            await process.communicate()
            raise

        payload = self._read_payload(out_file)
        self.last_cookies = payload.get("cookies", []) if isinstance(payload.get("cookies"), list) else []
        self._merge_browser_cookies(self.last_cookies)
        try:
            out_file.unlink(missing_ok=True)
            if cookies_file:
                cookies_file.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(profile_dir, ignore_errors=True)
        if process.returncode != 0 or not payload.get("ok"):
            message = payload.get("error") or stderr.decode("utf-8", errors="replace")
            raise FetchNetworkError(f"browser fetch failed: {message}")
        html = str(payload.get("html", "") or "")
        if self._looks_like_challenge(html):
            raise BrowserRequired("browser verification required", url=str(payload.get("url") or url), body_sample=html[:1000])
        return html

    def _playwright_cookies(self) -> list[dict[str, Any]]:
        cookies: list[dict[str, Any]] = []
        for domain, jar in self.cookies.items():
            if not isinstance(jar, dict):
                continue
            clean_domain = str(domain or "").strip().lstrip(".")
            if not clean_domain:
                continue
            for name, value in jar.items():
                if not name:
                    continue
                cookies.append({
                    "name": str(name),
                    "value": str(value),
                    "domain": clean_domain,
                    "path": "/",
                })
        return cookies

    def _merge_browser_cookies(self, cookies: list[dict[str, Any]]) -> None:
        for item in cookies:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain", "")).strip().lstrip(".")
            name = str(item.get("name", ""))
            value = str(item.get("value", ""))
            if not domain or not name:
                continue
            self.cookies.setdefault(domain, {})[name] = value

    def _read_payload(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _looks_like_challenge(self, html: str) -> bool:
        return looks_like_any_challenge(html)
