from __future__ import annotations

import asyncio
import json
from typing import NoReturn

from dotenv import load_dotenv

from .brightspace import BrightspaceClient


async def _run() -> int:
    client = BrightspaceClient.from_env()
    try:
        who = await client.whoami()
        print("whoami:")
        print(json.dumps(who, indent=2))

        courses = await client.list_courses(page_size=5)
        print("\nlist_courses (first 5):")
        print(json.dumps(courses, indent=2))
        return 0
    except Exception as e:
        print(f"Self-test failed: {e}")
        return 1


def cli() -> NoReturn:
    load_dotenv()
    code = asyncio.run(_run())
    raise SystemExit(code)

