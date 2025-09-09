import asyncio
import os
import types
import pytest

from brightspace_mcp.brightspace import BrightspaceClient


@pytest.mark.unit
def test_build_path_defaults():
    c = BrightspaceClient(
        base_url="https://example.com",
        client_id="x",
        client_secret="y",
        refresh_token="z",
        lp_version="1.46",
        le_version="1.74",
    )
    assert c.build_path("lp", "/users/whoami") == "/d2l/api/lp/1.46/users/whoami"
    assert c.build_path("le", "content/toc") == "/d2l/api/le/1.74/content/toc"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_version_fallback_order(monkeypatch):
    c = BrightspaceClient(
        base_url="https://example.com",
        client_id="x",
        client_secret="y",
        refresh_token="z",
        lp_version="1.46",
        le_version="1.74",
    )
    c.le_versions = ["1.80", "1.74", "1.70"]

    calls = []

    async def fake_request(method, path, *, params=None, json=None, headers=None, expect_json=True):
        calls.append((method, path))
        # First two versions 404; third succeeds
        if path.startswith("/d2l/api/le/1.80/"):
            return 404, {"error": "not found"}, {}
        if path.startswith("/d2l/api/le/1.74/"):
            return 410, {"error": "gone"}, {}
        return 200, {"ok": True}, {}

    monkeypatch.setattr(c, "request", fake_request)

    code, data, _ = await c.le("GET", "/123/grades/")
    assert code == 200 and data == {"ok": True}
    # Ensure tried in order and stopped after success
    assert calls[0][1].startswith("/d2l/api/le/1.80/")
    assert calls[1][1].startswith("/d2l/api/le/1.74/")
    assert calls[2][1].startswith("/d2l/api/le/1.70/")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_paginate_bookmark(monkeypatch):
    c = BrightspaceClient(
        base_url="https://example.com",
        client_id="x",
        client_secret="y",
        refresh_token="z",
    )

    pages = [
        (200, {"Items": [1, 2], "Bookmark": "b1"}, {}),
        (200, {"Items": [3], "Bookmark": None}, {}),
    ]
    idx = {"i": 0}

    async def fake_request(method, path, *, params=None, json=None, headers=None, expect_json=True):
        i = idx["i"]
        idx["i"] = i + 1
        return pages[i]

    monkeypatch.setattr(c, "request", fake_request)

    out = await c.paginate_bookmark("/d2l/api/lp/1.46/courses/", page_size=2)
    assert out["status"] == 200
    assert out["items"] == [1, 2, 3]
    assert out["bookmarks"] == ["b1"]

