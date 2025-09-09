# brightspace_mcp/brightspace.py
from __future__ import annotations

import os
import time
import json
import base64
from typing import Any, Dict, Mapping, Optional, Tuple, Union

import httpx

Json = Union[Dict[str, Any], list, str, int, float, bool, None]


class BrightspaceClient:
    """
    Minimal Brightspace REST client:
    - OAuth refresh-token flow
    - Generic request() for ANY API path
    - 401 refresh retry + basic 429 backoff
    - Bookmark pagination helper
    - Upload/download helpers
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        lp_version: str = "1.46",
        le_version: str = "1.74",
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.lp_version = lp_version
        self.le_version = le_version
        self.lp_versions: list[str] = [v.strip() for v in os.environ.get("BS_LP_VERSION_CANDIDATES", lp_version).split(",") if v.strip()]
        self.le_versions: list[str] = [v.strip() for v in os.environ.get("BS_LE_VERSION_CANDIDATES", le_version).split(",") if v.strip()]
        self.timeout = timeout
        self.max_retries = max_retries
        self._access_token: Optional[str] = None

    @classmethod
    def from_env(cls) -> "BrightspaceClient":
        return cls(
            base_url=os.environ["BS_BASE_URL"],
            client_id=os.environ["BS_CLIENT_ID"],
            client_secret=os.environ["BS_CLIENT_SECRET"],
            refresh_token=os.environ["BS_REFRESH_TOKEN"],
            lp_version=os.environ.get("BS_LP_VERSION", "1.46"),
            le_version=os.environ.get("BS_LE_VERSION", "1.74"),
        )

    # ---------- auth ----------

    async def _refresh_access_token(self) -> str:
        # Try multiple token endpoints in order until success.
        # Priority: BS_TOKEN_URL (if provided) -> tenant endpoints -> global BAS
        candidates: list[str] = []
        override = os.environ.get("BS_TOKEN_URL")
        if override:
            candidates.append(override)
        # Tenant-local common endpoints
        base = self.base_url.rstrip("/")
        candidates.append(f"{base}/d2l/oauth2/token")
        candidates.append(f"{base}/d2l/auth/api/token")
        # Global BAS
        candidates.append("https://auth.brightspace.com/core/connect/token")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        last_err: Optional[str] = None
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for url in candidates:
                try:
                    r = await client.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
                except httpx.RequestError as e:
                    last_err = f"request error: {e}"
                    continue

                ctype = r.headers.get("content-type", "")
                body: Any
                try:
                    body = r.json() if "application/json" in ctype else r.text
                except Exception:
                    body = r.text

                if r.status_code == 200 and isinstance(body, dict) and "access_token" in body:
                    self._access_token = body["access_token"]
                    return self._access_token

                # 404/410 or redirect to error page → try next
                if r.status_code in (404, 410, 302):
                    last_err = f"{r.status_code} at {url}"
                    continue

                # 400 usually means invalid_grant/invalid_client for a valid endpoint
                if r.status_code == 400:
                    last_err = f"400 at {url}: {body}"
                    break

                # Any other error, keep note and try next
                last_err = f"{r.status_code} at {url}: {body}"
                continue

        raise httpx.HTTPStatusError(
            f"Failed to refresh token. Last error: {last_err}", request=None, response=None
        )

    async def _auth_headers(self, extra: Optional[Mapping[str, str]] = None) -> Mapping[str, str]:
        if not self._access_token:
            await self._refresh_access_token()
        base = {"Authorization": f"Bearer {self._access_token}"}
        if extra:
            base.update(extra)
        return base

    # ---------- core request ----------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Optional[Json] = None,
        headers: Optional[Mapping[str, str]] = None,
        expect_json: bool = True,
    ) -> Tuple[int, Json, Mapping[str, str]]:
        """
        Generic call for ANY Brightspace API.
        - path: '/d2l/api/...'
        Returns: (status_code, parsed_json_or_text_or_bytes_b64, response_headers)
        """
        if not path.startswith("/"):
            raise ValueError("path must start with '/'")
        url = f"{self.base_url}{path}"

        retries = 0
        last_exc: Optional[Exception] = None

        while retries <= self.max_retries:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.request(
                        method.upper(),
                        url,
                        params=params,
                        json=json,
                        headers=await self._auth_headers(headers),
                    )

                # 401 → refresh once then retry
                if r.status_code == 401 and retries < self.max_retries:
                    await self._refresh_access_token()
                    retries += 1
                    continue

                # 429 → respect Retry-After and backoff
                if r.status_code == 429 and retries < self.max_retries:
                    delay = 1.0
                    ra = r.headers.get("Retry-After")
                    if ra:
                        try:
                            delay = float(ra)
                        except ValueError:
                            pass
                    time.sleep(delay)
                    retries += 1
                    continue

                # success or non-retriable error
                ctype = r.headers.get("content-type", "")
                if expect_json and "application/json" in ctype:
                    body: Json = r.json()
                elif "application/json" in ctype:
                    body = r.json()
                elif "text/" in ctype:
                    body = r.text
                else:
                    # binary → base64 so MCP can return JSON
                    body = base64.b64encode(r.content).decode("ascii")

                return r.status_code, body, dict(r.headers)

            except httpx.RequestError as e:
                last_exc = e
                retries += 1

        # exhaust
        if last_exc:
            raise last_exc
        raise RuntimeError("request failed after retries")

    # ---------- helpers ----------

    def build_path(self, service: str, tail: str, *, version: Optional[str] = None) -> str:
        """
        service: 'lp' or 'le' (or any Brightspace service root)
        tail: e.g. '/users/whoami' or '/courses/'
        """
        ver = version or (self.lp_version if service == "lp" else self.le_version)
        if not tail.startswith("/"):
            tail = "/" + tail
        return f"/d2l/api/{service}/{ver}{tail}"

    async def _request_with_version_fallback(
        self,
        service: str,
        method: str,
        tail: str,
        *,
        versions: Optional[list[str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        json: Optional[Json] = None,
        headers: Optional[Mapping[str, str]] = None,
        expect_json: bool = True,
    ) -> Tuple[int, Json, Mapping[str, str]]:
        """
        Try a list of versions for a service until one succeeds or non-version error occurs.
        Treat 404/410 as version-mismatch and continue to next candidate.
        """
        candidates = list(versions or (self.lp_versions if service == "lp" else self.le_versions))
        seen: set[str] = set()
        # Ensure the default service version is tried first
        preferred = self.lp_version if service == "lp" else self.le_version
        if preferred not in candidates:
            candidates.insert(0, preferred)
        # Deduplicate while preserving order
        uniq: list[str] = []
        for v in candidates:
            if v not in seen:
                seen.add(v)
                uniq.append(v)

        last: Tuple[int, Json, Mapping[str, str]] | None = None
        for ver in uniq:
            code, data, hdrs = await self.request(
                method,
                self.build_path(service, tail, version=ver),
                params=params,
                json=json,
                headers=headers,
                expect_json=expect_json,
            )
            last = (code, data, hdrs)
            if code in (404, 410):
                continue
            return code, data, hdrs
        assert last is not None
        return last

    # Convenience helpers
    async def le(
        self,
        method: str,
        tail: str,
        *,
        versions: Optional[list[str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        json: Optional[Json] = None,
        headers: Optional[Mapping[str, str]] = None,
        expect_json: bool = True,
    ) -> Tuple[int, Json, Mapping[str, str]]:
        return await self._request_with_version_fallback("le", method, tail, versions=versions, params=params, json=json, headers=headers, expect_json=expect_json)

    async def lp(
        self,
        method: str,
        tail: str,
        *,
        versions: Optional[list[str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        json: Optional[Json] = None,
        headers: Optional[Mapping[str, str]] = None,
        expect_json: bool = True,
    ) -> Tuple[int, Json, Mapping[str, str]]:
        return await self._request_with_version_fallback("lp", method, tail, versions=versions, params=params, json=json, headers=headers, expect_json=expect_json)

    async def paginate_bookmark(
        self,
        path: str,
        *,
        page_size: int = 100,
        max_pages: int = 10,
        params: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged: list = []
        bookmarks: list = []
        bookmark: Optional[str] = None
        base_params: Dict[str, Any] = {"pageSize": page_size}
        if params:
            base_params.update(params)
        for _ in range(max_pages):
            prms = dict(base_params)
            if bookmark:
                prms["bookmark"] = bookmark
            code, data, _ = await self.request("GET", path, params=prms)
            if code >= 400 or not isinstance(data, dict):
                return {"status": code, "data": data}
            items = data.get("Items") or data.get("items") or []
            merged.extend(items)
            bookmark = data.get("Bookmark") or data.get("Next") or data.get("bookmark")
            if bookmark:
                bookmarks.append(bookmark)
            if not bookmark:
                break
        return {"status": 200, "items": merged, "bookmarks": bookmarks, "last_bookmark": bookmark}

    async def upload_multipart(
        self,
        path: str,
        *,
        fields: Mapping[str, Any],
        files: Mapping[str, Tuple[str, bytes, str]],  # name -> (filename, content, mime)
        headers: Optional[Mapping[str, str]] = None,
    ) -> Tuple[int, Json, Mapping[str, str]]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                url,
                data=fields,
                files={k: v for k, v in files.items()},
                headers=await self._auth_headers(headers),
            )
        ctype = r.headers.get("content-type", "")
        body: Json = r.json() if "application/json" in ctype else r.text
        return r.status_code, body, dict(r.headers)

    async def download_bytes_b64(self, path: str, *, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        code, data, headers = await self.request("GET", path, params=params, expect_json=False)
        return {"status": code, "data_b64": data, "headers": headers}

    # ---------- opinionated wrappers (safe, tested routes) ----------

    async def whoami(self) -> Dict[str, Any]:
        code, data, _ = await self.lp("GET", "/users/whoami")
        if code >= 400:
            raise RuntimeError(f"whoami failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def list_courses(self, page_size: int = 10, bookmark: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        code, data, _ = await self.lp("GET", "/courses/", params=params)
        if code >= 400:
            raise RuntimeError(f"list_courses failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def create_announcement(self, org_unit_id: int, title: str, html: str) -> Dict[str, Any]:
        payload = {"Title": title, "IsPublished": True, "Body": {"Content": html, "Type": "Html"}}
        code, data, _ = await self.le("POST", f"/{org_unit_id}/news/", json=payload)
        if code >= 400:
            raise RuntimeError(f"create_announcement failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def list_org_units(
        self,
        *,
        page_size: int = 100,
        bookmark: Optional[str] = None,
        org_unit_type_id: Optional[int] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        if org_unit_type_id is not None:
            params["orgUnitTypeId"] = org_unit_type_id
        if search:
            params["search"] = search
        code, data, _ = await self.lp("GET", "/orgstructure/", params=params)
        if code >= 400:
            raise RuntimeError(f"list_org_units failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def list_users(
        self,
        *,
        page_size: int = 100,
        bookmark: Optional[str] = None,
        search_term: Optional[str] = None,
        org_unit_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        if search_term:
            params["searchTerm"] = search_term
        if org_unit_id is not None:
            params["orgUnitId"] = org_unit_id
        code, data, _ = await self.lp("GET", "/users/", params=params)
        if code >= 400:
            raise RuntimeError(f"list_users failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        code, data, _ = await self.lp("GET", f"/users/{user_id}")
        if code >= 400:
            raise RuntimeError(f"get_user failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def my_enrollments(self, page_size: int = 100, bookmark: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        code, data, _ = await self.lp("GET", "/enrollments/myenrollments/", params=params)
        if code >= 400:
            raise RuntimeError(f"my_enrollments failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def list_announcements(self, org_unit_id: int, page_size: int = 100, bookmark: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        code, data, _ = await self.le("GET", f"/{org_unit_id}/news/", params=params)
        if code >= 400:
            raise RuntimeError(f"list_announcements failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def get_content_toc(self, org_unit_id: int) -> Dict[str, Any]:
        code, data, _ = await self.le("GET", f"/{org_unit_id}/content/toc")
        if code >= 400:
            raise RuntimeError(f"get_content_toc failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    # ---------- discussions ----------

    async def list_discussion_forums(self, org_unit_id: int) -> Dict[str, Any]:
        code, data, _ = await self.le("GET", f"/{org_unit_id}/discussions/forums/")
        if code >= 400:
            raise RuntimeError(f"list_discussion_forums failed: {code} {data}")
        assert isinstance(data, (list, dict))
        return data  # API may return list

    async def list_discussion_topics(self, org_unit_id: int) -> Dict[str, Any]:
        code, data, _ = await self.le("GET", f"/{org_unit_id}/discussions/topics/")
        if code >= 400:
            raise RuntimeError(f"list_discussion_topics failed: {code} {data}")
        assert isinstance(data, (list, dict))
        return data

    # ---------- quizzes ----------

    async def list_quizzes(self, org_unit_id: int, page_size: int = 100, bookmark: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        code, data, _ = await self.le("GET", f"/{org_unit_id}/quizzes/quizzes/", params=params)
        if code >= 400:
            raise RuntimeError(f"list_quizzes failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def get_quiz(self, org_unit_id: int, quiz_id: int) -> Dict[str, Any]:
        code, data, _ = await self.le("GET", f"/{org_unit_id}/quizzes/quizzes/{quiz_id}")
        if code >= 400:
            raise RuntimeError(f"get_quiz failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    # ---------- content topic files ----------

    async def get_content_topic(self, org_unit_id: int, topic_id: int) -> Dict[str, Any]:
        code, data, _ = await self.le("GET", f"/{org_unit_id}/content/topics/{topic_id}")
        if code >= 400:
            raise RuntimeError(f"get_content_topic failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def download_content_topic_file_b64(self, org_unit_id: int, topic_id: int) -> Dict[str, Any]:
        return await self.download_bytes_b64(self.build_path("le", f"/{org_unit_id}/content/topics/{topic_id}/file"))

    # ---------- grades (common views; endpoints may vary by version/tenant) ----------

    async def list_grade_items(self, org_unit_id: int) -> Dict[str, Any]:
        code, data, _ = await self.le("GET", f"/{org_unit_id}/grades/")
        if code >= 400:
            raise RuntimeError(f"list_grade_items failed: {code} {data}")
        return data  # may be list or dict depending on version

    async def get_user_grades(self, org_unit_id: int, user_id: int) -> Dict[str, Any]:
        code, data, _ = await self.le("GET", f"/{org_unit_id}/grades/values/user/{user_id}/")
        if code >= 400:
            raise RuntimeError(f"get_user_grades failed: {code} {data}")
        return data

    # ---------- write helpers (raw bodies) ----------

    async def create_discussion_forum(self, org_unit_id: int, body: Json) -> Dict[str, Any]:
        code, data, _ = await self.le("POST", f"/{org_unit_id}/discussions/forums/", json=body)
        if code >= 400:
            raise RuntimeError(f"create_discussion_forum failed: {code} {data}")
        assert isinstance(data, (dict, list, str))
        return data

    async def create_discussion_topic(self, org_unit_id: int, body: Json) -> Dict[str, Any]:
        code, data, _ = await self.le("POST", f"/{org_unit_id}/discussions/topics/", json=body)
        if code >= 400:
            raise RuntimeError(f"create_discussion_topic failed: {code} {data}")
        assert isinstance(data, (dict, list, str))
        return data

    async def create_grade_item(self, org_unit_id: int, body: Json) -> Dict[str, Any]:
        code, data, _ = await self.le("POST", f"/{org_unit_id}/grades/", json=body)
        if code >= 400:
            raise RuntimeError(f"create_grade_item failed: {code} {data}")
        return data

    async def upsert_user_grade_value(self, org_unit_id: int, user_id: int, body: Json, method: str = "PUT") -> Dict[str, Any]:
        method = method.upper()
        if method not in ("PUT", "POST"):
            raise ValueError("method must be PUT or POST")
        code, data, _ = await self.le(method, f"/{org_unit_id}/grades/values/user/{user_id}/", json=body)
        if code >= 400:
            raise RuntimeError(f"upsert_user_grade_value failed: {code} {data}")
        return data
