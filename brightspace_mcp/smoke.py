from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
from typing import Dict, Tuple, Any, Optional


async def run_smoke(
    command: str,
    args: list[str],
    env: Dict[str, str],
    timeout: float = 30.0,
) -> int:
    try:
        from mcp.client.stdio import stdio_client
        from mcp.client.session import ClientSession
    except Exception as e:
        print("MCP client not available: please ensure 'mcp' package is installed.")
        print(f"Import error: {e}")
        return 2

    async with stdio_client(command, args=args, env={**os.environ, **env}) as (read, write):
        async with ClientSession(read, write) as session:
            tools = await session.list_tools()
            print("Tools exposed:")
            for t in tools.tools:
                print(f"- {t.name}")

            async def call(tool: str, arguments: Optional[Dict[str, Any]] = None):
                print(f"\n==> {tool} {json.dumps(arguments or {})}")
                res = await session.call_tool(tool, arguments or {})
                print(json.dumps(res.content[0].json, indent=2) if res.content else res)

            await call("bs.whoami")
            await call("bs.list_courses", {"page_size": 5})
            await call("bs.list_org_units", {"org_unit_type_id": 3, "page_size": 5})
            await call("bs.list_users", {"page_size": 5})
            return 0


def cli() -> None:
    # Reads config from environment variables for convenience
    command = os.getenv("MCP_SMOKE_COMMAND") or sys.argv[1] if len(sys.argv) > 1 else "brightspace-mcp"
    args = shlex.split(os.getenv("MCP_SMOKE_ARGS") or "--stdio")
    env = {
        k: os.getenv(k)
        for k in [
            "BS_BASE_URL",
            "BS_CLIENT_ID",
            "BS_CLIENT_SECRET",
            "BS_REFRESH_TOKEN",
            "BS_LP_VERSION",
            "BS_LE_VERSION",
            "BS_LP_VERSION_CANDIDATES",
            "BS_LE_VERSION_CANDIDATES",
        ]
        if os.getenv(k) is not None
    }
    code = asyncio.run(run_smoke(command, args, env))
    raise SystemExit(code)

