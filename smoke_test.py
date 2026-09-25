from __future__ import annotations

import asyncio
import os

from mcp import Client


async def main() -> None:
    url = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp")
    async with Client(url) as client:
        tools = await client.list_tools()
        names = [tool.name for tool in tools.tools]
        print(f"Connected to {url}")
        print("Tools:", ", ".join(names))


if __name__ == "__main__":
    asyncio.run(main())
