from __future__ import annotations

import argparse
import asyncio
import math
import os

from mcp import Client

# 도구 목록까지 확인해 이전 버전의 서버가 남아 있는 경우를 잡는다.
EXPECTED_TOOLS = {"run_command"}


async def check_mcp(url: str) -> None:
    async with Client(url) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}

        if names != EXPECTED_TOOLS:
            raise RuntimeError(
                f"unexpected MCP tools: expected {sorted(EXPECTED_TOOLS)}, "
                f"got {sorted(names)}"
            )

    print(f"Connected to {url}")
    print("Tools:", ", ".join(sorted(names)))


async def main(wait_seconds: float = 0) -> None:
    url = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp")
    if wait_seconds == 0:
        await check_mcp(url)
        return

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while True:
        try:
            # 연결 시도당 최대 5초, 전체 대기는 남은 제한 시간 안에서 끝낸다.
            await asyncio.wait_for(
                check_mcp(url), timeout=max(0, min(5, deadline - loop.time()))
            )
            return
        except Exception as exc:
            remaining = deadline - loop.time()
            if remaining > 0:
                await asyncio.sleep(min(1, remaining))
            if loop.time() >= deadline:
                raise RuntimeError(
                    f"MCP did not become ready within {wait_seconds:g} seconds"
                ) from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check MCP connectivity and tool list")
    parser.add_argument(
        "--wait-seconds", type=float, default=0,
        help="retry until ready for this many seconds (default: one attempt)",
    )
    args = parser.parse_args()
    if not math.isfinite(args.wait_seconds) or args.wait_seconds < 0:
        parser.error("--wait-seconds must be a finite, non-negative number")
    asyncio.run(main(args.wait_seconds))
