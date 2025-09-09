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
        url = "https://auth.brightspace.com/core/connect/token"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            self._access_token = r.json()["access_token"]
            return self._access_token

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
        code, data, _ = await self.request("GET", self.build_path("lp", "/users/whoami"))
        if code >= 400:
            raise RuntimeError(f"whoami failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def list_courses(self, page_size: int = 10, bookmark: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        code, data, _ = await self.request("GET", self.build_path("lp", "/courses/"), params=params)
        if code >= 400:
            raise RuntimeError(f"list_courses failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def create_announcement(self, org_unit_id: int, title: str, html: str) -> Dict[str, Any]:
        payload = {"Title": title, "IsPublished": True, "Body": {"Content": html, "Type": "Html"}}
        code, data, _ = await self.request("POST", self.build_path("le", f"/{org_unit_id}/news/"), json=payload)
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
        code, data, _ = await self.request("GET", self.build_path("lp", "/orgstructure/"), params=params)
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
        code, data, _ = await self.request("GET", self.build_path("lp", "/users/"), params=params)
        if code >= 400:
            raise RuntimeError(f"list_users failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        code, data, _ = await self.request("GET", self.build_path("lp", f"/users/{user_id}"))
        if code >= 400:
            raise RuntimeError(f"get_user failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def my_enrollments(self, page_size: int = 100, bookmark: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        code, data, _ = await self.request("GET", self.build_path("lp", "/enrollments/myenrollments/"), params=params)
        if code >= 400:
            raise RuntimeError(f"my_enrollments failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def list_announcements(self, org_unit_id: int, page_size: int = 100, bookmark: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        code, data, _ = await self.request("GET", self.build_path("le", f"/{org_unit_id}/news/"), params=params)
        if code >= 400:
            raise RuntimeError(f"list_announcements failed: {code} {data}")
        assert isinstance(data, dict)
        return data

    async def get_content_toc(self, org_unit_id: int) -> Dict[str, Any]:
        code, data, _ = await self.request("GET", self.build_path("le", f"/{org_unit_id}/content/toc"))
        if code >= 400:
            raise RuntimeError(f"get_content_toc failed: {code} {data}")
        assert isinstance(data, dict)
        return data
