"""Tests for frontend static file serving."""

import re

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_console_spa_served():
    res = client.get("/console")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "LegadoHub" in res.text or "root" in res.text


def test_console_catchall_served():
    res = client.get("/console/plugins")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


def test_console_dist_assets_are_served():
    html = client.get("/console").text
    asset_paths = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    assert asset_paths
    for path in asset_paths:
        res = client.get(path)
        assert res.status_code == 200, path


def test_console_stylesheet_contains_tailwind_utilities():
    html = client.get("/console").text
    stylesheet_paths = re.findall(r'href="(/assets/[^"]+\.css)"', html)
    assert stylesheet_paths
    css = "\n".join(client.get(path).text for path in stylesheet_paths)
    assert "@tailwind utilities" not in css
    assert ".flex{" in css
    assert ".grid{" in css
    assert ".p-6{" in css


def test_console_favicon_served():
    res = client.get("/favicon.svg")
    assert res.status_code == 200
    assert "image/svg" in res.headers.get("content-type", "")


def test_legacy_admin_spa_entry_not_exposed():
    res = client.get("/admin")
    assert res.status_code == 404






