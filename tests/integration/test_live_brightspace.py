import os
import json
import pytest

from brightspace_mcp.brightspace import BrightspaceClient


LIVE_ENV_VARS = [
    "BS_BASE_URL",
    "BS_CLIENT_ID",
    "BS_CLIENT_SECRET",
    "BS_REFRESH_TOKEN",
]


def has_live_env() -> bool:
    return all(os.getenv(k) for k in LIVE_ENV_VARS)


live = pytest.mark.skipif(not has_live_env(), reason="Live Brightspace env vars not set")


@live
@pytest.mark.asyncio
async def test_whoami_and_list_courses_live():
    c = BrightspaceClient.from_env()
    me = await c.whoami()
    assert isinstance(me, dict)
    courses = await c.list_courses(page_size=5)
    assert isinstance(courses, dict)
    # Basic schema smoke checks
    assert "Items" in courses or "items" in courses

