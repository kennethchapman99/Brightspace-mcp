import os
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


def pick_ou_id_from_payload(payload) -> int | None:
    # Try common shapes seen in Brightspace responses
    if isinstance(payload, dict):
        items = payload.get("Items") or payload.get("items") or []
        for it in items:
            # direct id
            for key in ("OrgUnitId", "Identifier", "Id", "id"):
                v = it.get(key) if isinstance(it, dict) else None
                if isinstance(v, int):
                    return v
            # nested orgunit object
            ou = it.get("OrgUnit") if isinstance(it, dict) else None
            if isinstance(ou, dict):
                for key in ("Id", "Identifier", "OrgUnitId"):
                    v = ou.get(key)
                    if isinstance(v, int):
                        return v
    return None


@live
@pytest.mark.asyncio
async def test_quizzes_discussions_grades_smoke():
    c = BrightspaceClient.from_env()
    me = await c.whoami()
    my_id = me.get("UserId") or me.get("Identifier") or me.get("Id")

    # Determine a course OU
    test_ou_env = os.getenv("BS_TEST_OU_ID")
    if test_ou_env and test_ou_env.isdigit():
        ou = int(test_ou_env)
    else:
        courses = await c.list_courses(page_size=5)
        ou = pick_ou_id_from_payload(courses)
        if ou is None:
            ous = await c.list_org_units(page_size=5, org_unit_type_id=3)
            ou = pick_ou_id_from_payload(ous)
    assert isinstance(ou, int)

    # Quizzes
    quizzes = await c.list_quizzes(ou, page_size=5)
    assert isinstance(quizzes, dict)
    first_qid = None
    for it in quizzes.get("Items", []) or quizzes.get("items", []) or []:
        qid = it.get("Id") or it.get("QuizId") or it.get("id")
        if isinstance(qid, int):
            first_qid = qid
            break
    if first_qid:
        q = await c.get_quiz(ou, first_qid)
        assert isinstance(q, dict)

    # Discussions
    forums = await c.list_discussion_forums(ou)
    assert isinstance(forums, (list, dict))
    topics = await c.list_discussion_topics(ou)
    assert isinstance(topics, (list, dict))

    # Grades
    items = await c.list_grade_items(ou)
    assert isinstance(items, (list, dict))

    if isinstance(my_id, int):
        vals = await c.get_user_grades(ou, my_id)
        assert isinstance(vals, (list, dict))


@live
@pytest.mark.asyncio
async def test_negative_paths_nonexistent_ou():
    c = BrightspaceClient.from_env()
    # Try a very large OU id to avoid collisions
    bogus_ou = 999999999
    code, _, _ = await c.le("GET", f"/{bogus_ou}/content/toc")
    assert code >= 400

