import pytest

from brightspace_mcp.brightspace import BrightspaceClient


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wrappers_raise_on_error(monkeypatch):
    c = BrightspaceClient(
        base_url="https://example.com",
        client_id="x",
        client_secret="y",
        refresh_token="z",
    )

    async def err_req(method, path, *, params=None, json=None, headers=None, expect_json=True):
        return 500, {"error": "boom"}, {}

    # Patch version-aware helpers to simulate error
    monkeypatch.setattr(c, "lp", lambda *a, **k: err_req(*a, **k))
    monkeypatch.setattr(c, "le", lambda *a, **k: err_req(*a, **k))

    with pytest.raises(RuntimeError):
        await c.whoami()

    with pytest.raises(RuntimeError):
        await c.list_courses()

    with pytest.raises(RuntimeError):
        await c.create_announcement(123, "t", "h")

