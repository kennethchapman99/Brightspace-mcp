from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Dict, Optional, NoReturn

from dotenv import load_dotenv

from .brightspace import BrightspaceClient


async def _whoami(client: BrightspaceClient) -> int:
    data = await client.whoami()
    print(json.dumps(data, indent=2))
    return 0


async def _list_courses(client: BrightspaceClient, page_size: int, bookmark: Optional[str]) -> int:
    data = await client.list_courses(page_size=page_size, bookmark=bookmark)
    print(json.dumps(data, indent=2))
    return 0


async def _create_announcement(client: BrightspaceClient, org_unit_id: int, title: str, html: str) -> int:
    data = await client.create_announcement(org_unit_id=org_unit_id, title=title, html=html)
    print(json.dumps(data, indent=2))
    return 0


async def _api_call(
    client: BrightspaceClient,
    method: str,
    path: str,
    params: Optional[str],
    body: Optional[str],
    headers: Optional[str],
) -> int:
    prms: Optional[Dict[str, Any]] = json.loads(params) if params else None
    bdy: Optional[Dict[str, Any]] = json.loads(body) if body else None
    hdrs: Optional[Dict[str, str]] = json.loads(headers) if headers else None
    status, data, resp_headers = await client.request(method, path, params=prms, json=bdy, headers=hdrs)
    print(json.dumps({"status": status, "data": data, "headers": dict(resp_headers)}, indent=2))
    return 0 if status < 400 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="brightspace-mcp-cli", description="Direct CLI for Brightspace MCP helpers")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="Show authenticated user")

    p_list = sub.add_parser("list-courses", help="List courses with optional paging")
    p_list.add_argument("--page-size", type=int, default=10)
    p_list.add_argument("--bookmark", type=str, default=None)

    p_ann = sub.add_parser("create-announcement", help="Create a course announcement")
    p_ann.add_argument("org_unit_id", type=int)
    p_ann.add_argument("title", type=str)
    p_ann.add_argument("html", type=str)

    p_api = sub.add_parser("api-call", help="Generic API call: method + path + optional JSON strings")
    p_api.add_argument("method", type=str)
    p_api.add_argument("path", type=str)
    p_api.add_argument("--params", type=str, help="JSON object string for query params")
    p_api.add_argument("--body", type=str, help="JSON object string for request body")
    p_api.add_argument("--headers", type=str, help="JSON object string for extra headers")

    return p


async def _run(args: argparse.Namespace) -> int:
    client = BrightspaceClient.from_env()
    if args.cmd == "whoami":
        return await _whoami(client)
    if args.cmd == "list-courses":
        return await _list_courses(client, args.page_size, args.bookmark)
    if args.cmd == "create-announcement":
        return await _create_announcement(client, args.org_unit_id, args.title, args.html)
    if args.cmd == "api-call":
        return await _api_call(client, args.method, args.path, args.params, args.body, args.headers)
    raise SystemExit(2)


def cli() -> NoReturn:
    load_dotenv()
    p = build_parser()
    ns = p.parse_args()
    code = asyncio.run(_run(ns))
    raise SystemExit(code)

