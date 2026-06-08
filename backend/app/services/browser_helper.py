"""Launch a visible Playwright browser for manual challenge verification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class BrowserHelperService:
    """Start helper browser processes and import captured cookies."""

    def __init__(self, root_dir: Path | None = None):
        self.root_dir = root_dir or Path(__file__).resolve().parents[3]
        self.backend_dir = self.root_dir / "backend"
        self.frontend_dir = self.root_dir / "frontend"
        self.output_dir = self.backend_dir / "data" / "browser_challenges"
        self.script_path = self.backend_dir / "scripts" / "browser_challenge_helper.mjs"
        self.source_pool_path = self.backend_dir / "config" / "source_pool.json"

    def start(self, session: dict) -> dict:
        session_id = session.get("sessionId", "")
        open_url = session.get("openUrl", "")
        if not session_id or not open_url:
            return {"started": False, "error": "验证会话缺少 sessionId 或 openUrl"}
        if not self.script_path.exists():
            return {"started": False, "error": f"浏览器助手脚本不存在: {self.script_path}"}
        if not (self.frontend_dir / "node_modules" / "playwright").exists():
            return {"started": False, "error": "Playwright 尚未安装，请先运行 start.bat 或在 frontend 执行 npm install"}
        out_file = self.cookie_file(session_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "node",
            str(self.script_path),
            "--session-id",
            session_id,
            "--url",
            open_url,
            "--out",
            str(out_file),
        ]
        for domain in session.get("cookieDomains", []) or []:
            cmd.extend(["--cookie-domain", str(domain)])
        proxy_url = self._proxy_url()
        if proxy_url:
            cmd.extend(["--proxy", proxy_url])
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(self.frontend_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except FileNotFoundError:
            return {"started": False, "error": "未找到 node，请先安装 Node.js"}
        return {
            "started": True,
            "sessionId": session_id,
            "pid": process.pid,
            "openUrl": open_url,
            "cookieFile": str(out_file),
            "proxyUsed": bool(proxy_url),
            "proxyUrl": proxy_url,
            "message": "已启动可见浏览器。完成验证后回到控制台点击导入浏览器 Cookie。",
        }

    def status(self, session_id: str) -> dict:
        cookie_file = self.cookie_file(session_id)
        data = self.read_cookie_file(session_id)
        return {
            "sessionId": session_id,
            "cookieFile": str(cookie_file),
            "exists": cookie_file.exists(),
            "cookieCount": data.get("cookieCount", 0) if data else 0,
            "cookieDomains": data.get("cookieDomains", []) if data else [],
            "cookieNames": data.get("cookieNames", []) if data else [],
            "clearanceDomains": data.get("clearanceDomains", []) if data else [],
            "updatedAt": data.get("updatedAt", "") if data else "",
            "status": data.get("status", "missing") if data else "missing",
            "proxyUsed": bool(data.get("proxyUsed")) if data else False,
        }

    def read_cookie_file(self, session_id: str) -> dict[str, Any]:
        cookie_file = self.cookie_file(session_id)
        if not cookie_file.exists():
            return {}
        try:
            data = json.loads(cookie_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def cookies(self, session_id: str) -> list[dict]:
        data = self.read_cookie_file(session_id)
        cookies = data.get("cookies", [])
        return cookies if isinstance(cookies, list) else []

    def cookie_file(self, session_id: str) -> Path:
        return self.output_dir / f"{session_id}.cookies.json"

    def _proxy_url(self) -> str:
        if not self.source_pool_path.exists():
            return ""
        try:
            data = json.loads(self.source_pool_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return ""
        proxy = data.get("proxy", {}) if isinstance(data, dict) else {}
        if not proxy.get("enabled"):
            return ""
        return str(proxy.get("url", "") or "")
