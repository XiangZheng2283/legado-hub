"""DOM and network normalization helpers for Source Access Bridge."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from app.services.access_bridge.models import DomSnapshot, NetworkEntry


class _SnapshotParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.forms: list[dict[str, Any]] = []
        self.buttons: list[str] = []
        self._in_title = False
        self._in_button = False
        self._button_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "a" and attr_map.get("href"):
            self.links.append({"href": attr_map.get("href", ""), "text": ""})
        elif tag == "form":
            self.forms.append({
                "action": attr_map.get("action", ""),
                "method": attr_map.get("method", "get").upper(),
            })
        elif tag == "button":
            self._in_button = True
            self._button_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "button" and self._in_button:
            label = " ".join(part.strip() for part in self._button_text if part.strip())
            if label:
                self.buttons.append(label)
            self._in_button = False
            self._button_text = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
        if self._in_button:
            self._button_text.append(text)
        self.text_parts.append(text)
        if self.links and not self.links[-1]["text"]:
            self.links[-1]["text"] = text


def snapshot_from_html(html: str, *, url: str = "", text_limit: int = 8000) -> DomSnapshot:
    """Build a compact DOM snapshot without requiring browser runtime."""
    parser = _SnapshotParser()
    parser.feed(html or "")
    text = "\n".join(parser.text_parts)
    if len(text) > text_limit:
        text = text[:text_limit]
    return DomSnapshot(
        title=parser.title.strip(),
        url=url,
        text=text,
        links=parser.links,
        forms=parser.forms,
        buttons=parser.buttons,
    )


def normalize_network_entries(entries: list[dict[str, Any]]) -> list[NetworkEntry]:
    """Convert Playwright-like network dictionaries into typed entries."""
    normalized: list[NetworkEntry] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        normalized.append(
            NetworkEntry(
                url=str(entry.get("url", "")),
                method=str(entry.get("method", "GET")),
                status=int(entry.get("status", 0) or 0),
                resource_type=str(entry.get("resourceType", "") or entry.get("resource_type", "")),
                request_headers={
                    str(k): str(v) for k, v in (entry.get("requestHeaders") or {}).items()
                },
                response_headers={
                    str(k): str(v) for k, v in (entry.get("responseHeaders") or {}).items()
                },
            )
        )
    return normalized





