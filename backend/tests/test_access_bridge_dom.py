"""Tests for Source Access Bridge DOM and network helpers."""

from app.services.access_bridge.dom import normalize_network_entries, snapshot_from_html


def test_snapshot_from_html_extracts_compact_dom_fields():
    snapshot = snapshot_from_html(
        """
        <html>
          <head><title>验证页</title></head>
          <body>
            <a href="/book/1.htm">小说详情</a>
            <form action="/verify" method="post"></form>
            <button>继续</button>
          </body>
        </html>
        """,
        url="https://example.com",
    )

    assert snapshot.title == "验证页"
    assert snapshot.url == "https://example.com"
    assert snapshot.links == [{"href": "/book/1.htm", "text": "小说详情"}]
    assert snapshot.forms == [{"action": "/verify", "method": "POST"}]
    assert snapshot.buttons == ["继续"]


def test_normalize_network_entries_accepts_playwright_style_dicts():
    entries = normalize_network_entries([
        {
            "url": "https://example.com",
            "method": "POST",
            "status": 200,
            "resourceType": "document",
            "requestHeaders": {"Accept": "text/html"},
            "responseHeaders": {"Content-Type": "text/html"},
        }
    ])

    assert entries[0].url == "https://example.com"
    assert entries[0].method == "POST"
    assert entries[0].status == 200
    assert entries[0].resource_type == "document"
    assert entries[0].request_headers["Accept"] == "text/html"






