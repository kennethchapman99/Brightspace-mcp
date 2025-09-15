import pytest

from brightspace_mcp.brightspace import BrightspaceClient


def client() -> BrightspaceClient:
    return BrightspaceClient(
        base_url="https://example.com",
        client_id="id",
        client_secret="secret",
        refresh_token="rt",
        lp_version="1.46",
        le_version="1.74",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_course_enrollments(monkeypatch):
    c = client()
    seen = {}

    async def fake_request(method, path, *, params=None, json=None, headers=None, expect_json=True):
        seen.update(method=method, path=path, params=params)
        return 200, {"Items": []}, {}

    monkeypatch.setattr(c, "request", fake_request)
    out = await c.list_course_enrollments(123, page_size=50, bookmark="b1", role_id=7)
    assert out["Items"] == []
    assert seen["method"] == "GET"
    assert seen["path"].startswith("/d2l/api/lp/1.46/enrollments/orgUnits/123/")
    assert seen["params"]["pageSize"] == 50
    assert seen["params"]["bookmark"] == "b1"
    assert seen["params"]["roleId"] == 7


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enroll_and_unenroll_user(monkeypatch):
    c = client()
    calls = []

    async def fake_request(method, path, *, params=None, json=None, headers=None, expect_json=True):
        calls.append((method, path, json))
        if method == "DELETE":
            return 204, "", {}
        return 200, {"ok": True}, {}

    monkeypatch.setattr(c, "request", fake_request)

    res = await c.enroll_user(2001, 3002, 4003)
    assert res["ok"] is True
    m, p, j = calls[-1]
    assert m == "POST" and p.startswith("/d2l/api/lp/1.46/enrollments/")
    assert j == {"OrgUnitId": 2001, "UserId": 3002, "RoleId": 4003}

    code = await c.unenroll_user(2001, 3002)
    assert code == 204
    m, p, _ = calls[-1]
    assert m == "DELETE" and p.endswith("/enrollments/users/3002/orgUnits/2001")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_assignments_wrappers(monkeypatch):
    c = client()
    calls = []

    async def fake_request(method, path, *, params=None, json=None, headers=None, expect_json=True):
        calls.append((method, path, json))
        return 200, {"ok": True}, {}

    monkeypatch.setattr(c, "request", fake_request)

    await c.list_assignments(555)
    m, p, _ = calls[-1]
    assert m == "GET" and p.startswith("/d2l/api/le/1.74/555/dropbox/folders/")

    await c.get_assignment(555, 777)
    m, p, _ = calls[-1]
    assert m == "GET" and p.endswith("/dropbox/folders/777")

    await c.create_assignment(555, {"Name": "A1"})
    m, p, j = calls[-1]
    assert m == "POST" and p.endswith("/dropbox/folders/") and j == {"Name": "A1"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_courses_and_content_wrappers(monkeypatch):
    c = client()
    calls = []

    async def fake_request(method, path, *, params=None, json=None, headers=None, expect_json=True):
        calls.append((method, path, json))
        return 200, {"ok": True}, {}

    monkeypatch.setattr(c, "request", fake_request)

    await c.get_course_offering(42)
    m, p, _ = calls[-1]
    assert m == "GET" and p == "/d2l/api/lp/1.46/courses/42"

    await c.create_course_offering({"Name": "Course X"})
    m, p, j = calls[-1]
    assert m == "POST" and p == "/d2l/api/lp/1.46/courses/" and j["Name"] == "Course X"

    await c.create_content_module(42, {"Title": "Week 1"})
    m, p, j = calls[-1]
    assert m == "POST" and p == "/d2l/api/le/1.74/42/content/modules/" and j["Title"] == "Week 1"

    await c.create_content_topic(42, 99, {"Title": "Intro"})
    m, p, j = calls[-1]
    assert m == "POST" and p.endswith("/content/modules/99/structure/") and j["Title"] == "Intro"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_announcement_maintenance(monkeypatch):
    c = client()
    calls = []

    async def fake_request(method, path, *, params=None, json=None, headers=None, expect_json=True):
        calls.append((method, path, json))
        if method == "DELETE":
            return 204, "", {}
        return 200, {"ok": True}, {}

    monkeypatch.setattr(c, "request", fake_request)

    await c.update_announcement(77, 88, {"Title": "New"})
    m, p, j = calls[-1]
    assert m == "PUT" and p.endswith("/news/88") and j["Title"] == "New"

    code = await c.delete_announcement(77, 88)
    m, p, _ = calls[-1]
    assert code == 204 and m == "DELETE" and p.endswith("/news/88")

