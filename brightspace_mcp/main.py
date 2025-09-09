# brightspace_mcp/main.py
from __future__ import annotations

import os
import binascii
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .brightspace import BrightspaceClient

# Load .env so BS_* are available when launched by tools or AgentZero
load_dotenv()

mcp = FastMCP("Brightspace MCP")
bs = BrightspaceClient.from_env()

# ---------------------- Generic tools (cover ALL endpoints) ----------------------

@mcp.tool(
    name="bs.api_call",
    description=(
        "Call ANY Brightspace REST endpoint. "
        "Args: method, path (must start with /d2l/api/...), optional params, body, headers."
    ),
)
async def bs_api_call(
    method: str,
    path: str,
    params: Dict[str, Any] | None = None,
    body: Dict[str, Any] | None = None,
    headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    status, data, resp_headers = await bs.request(method, path, params=params, json=body, headers=headers)
    return {"status": status, "data": data, "headers": resp_headers}


@mcp.tool(
    name="bs.request",
    description=(
        "Alias for bs.api_call. Call ANY Brightspace REST endpoint. "
        "Args: method, path (must start with /d2l/api/...), optional params, body, headers."
    ),
)
async def bs_request(
    method: str,
    path: str,
    params: Dict[str, Any] | None = None,
    body: Dict[str, Any] | None = None,
    headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    return await bs_api_call(method=method, path=path, params=params, body=body, headers=headers)


@mcp.tool(
    name="bs.paginate",
    description=(
        "Bookmark pagination helper for list endpoints. "
        "Args: path, page_size=100, max_pages=10, params={}."
    ),
)
async def bs_paginate(
    path: str,
    page_size: int = 100,
    max_pages: int = 10,
    params: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return await bs.paginate_bookmark(path=path, page_size=page_size, max_pages=max_pages, params=params)


@mcp.tool(
    name="bs.build_path",
    description=(
        "Build a versioned API path. Args: service ('lp' or 'le'), tail (e.g. '/users/whoami'), "
        "version optional (defaults to env). Returns '/d2l/api/<service>/<ver><tail>'."
    ),
)
async def bs_build_path(service: str, tail: str, version: Optional[str] = None) -> Dict[str, str]:
    return {"path": bs.build_path(service, tail, version=version)}


@mcp.tool(
    name="bs.upload_multipart",
    description=(
        "Multipart upload to a Brightspace path. Args: path, fields (dict), "
        "files (dict name -> {filename, content_b64, mime})."
    ),
)
async def bs_upload_multipart(
    path: str,
    fields: Dict[str, Any] | None = None,
    files: Dict[str, Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    fields = fields or {}
    files = files or {}
    prepared = {}
    for name, spec in files.items():
        filename = spec["filename"]
        try:
            content = binascii.a2b_base64(spec["content_b64"])
        except binascii.Error as e:
            return {"status": 400, "error": f"Invalid base64 for file '{name}': {e}"}
        mime = spec.get("mime", "application/octet-stream")
        prepared[name] = (filename, content, mime)

    status, data, headers = await bs.upload_multipart(path, fields=fields, files=prepared)
    return {"status": status, "data": data, "headers": headers}


@mcp.tool(
    name="bs.download_b64",
    description=(
        "GET a binary resource and return base64. Args: path, optional params. "
        "Response: {status, data_b64, headers}."
    ),
)
async def bs_download_b64(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return await bs.download_bytes_b64(path, params=params)


# ---------------------- High-value wrappers (nice UX) ----------------------

@mcp.tool(name="bs.whoami", description="Return the current Brightspace user context.")
async def bs_whoami() -> Dict[str, Any]:
    return await bs.whoami()


@mcp.tool(name="bs.list_courses", description="List courses. Supports page_size and optional bookmark.")
async def bs_list_courses(page_size: int = 10, bookmark: str | None = None) -> Dict[str, Any]:
    return await bs.list_courses(page_size=page_size, bookmark=bookmark)


@mcp.tool(
    name="bs.create_announcement",
    description="Create a course announcement. Requires org_unit_id, title, html.",
)
async def bs_create_announcement(org_unit_id: int, title: str, html: str) -> Dict[str, Any]:
    return await bs.create_announcement(org_unit_id=org_unit_id, title=title, html=html)


@mcp.tool(
    name="bs.list_org_units",
    description=(
        "List organizational units. Args: page_size=100, bookmark, org_unit_type_id, search."
    ),
)
async def bs_list_org_units(
    page_size: int = 100,
    bookmark: str | None = None,
    org_unit_type_id: int | None = None,
    search: str | None = None,
) -> Dict[str, Any]:
    return await bs.list_org_units(page_size=page_size, bookmark=bookmark, org_unit_type_id=org_unit_type_id, search=search)


@mcp.tool(
    name="bs.list_users",
    description=(
        "List users. Args: page_size=100, bookmark, search_term, org_unit_id."
    ),
)
async def bs_list_users(
    page_size: int = 100,
    bookmark: str | None = None,
    search_term: str | None = None,
    org_unit_id: int | None = None,
) -> Dict[str, Any]:
    return await bs.list_users(page_size=page_size, bookmark=bookmark, search_term=search_term, org_unit_id=org_unit_id)


@mcp.tool(name="bs.get_user", description="Get a user by ID.")
async def bs_get_user(user_id: int) -> Dict[str, Any]:
    return await bs.get_user(user_id)


@mcp.tool(
    name="bs.my_enrollments",
    description="List current user's enrollments. Args: page_size=100, bookmark.",
)
async def bs_my_enrollments(page_size: int = 100, bookmark: str | None = None) -> Dict[str, Any]:
    return await bs.my_enrollments(page_size=page_size, bookmark=bookmark)


@mcp.tool(
    name="bs.list_announcements",
    description="List course announcements. Args: org_unit_id, page_size=100, bookmark.",
)
async def bs_list_announcements(org_unit_id: int, page_size: int = 100, bookmark: str | None = None) -> Dict[str, Any]:
    return await bs.list_announcements(org_unit_id=org_unit_id, page_size=page_size, bookmark=bookmark)


@mcp.tool(name="bs.get_content_toc", description="Get course Content TOC. Args: org_unit_id.")
async def bs_get_content_toc(org_unit_id: int) -> Dict[str, Any]:
    return await bs.get_content_toc(org_unit_id)


def cli() -> None:
    # FastMCP defaults to stdio. Blocking until the client disconnects.
    mcp.run()


if __name__ == "__main__":
    cli()
