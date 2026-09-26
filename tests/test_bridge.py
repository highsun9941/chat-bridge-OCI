"""Command and startup regressions; no root, systemd daemon, or tunnel keys needed."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import server
import smoke_test

ROOT = Path(__file__).resolve().parents[1]


class CommandResultTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workdir = Path(temp.name)
        workdir = patch.object(server, "DEFAULT_WORKDIR", self.workdir)
        workdir.start()
        self.addCleanup(workdir.stop)

    def test_exit_status_output_and_workdir(self) -> None:
        for code, cwd in [(0, "."), (7, str(self.workdir))]:
            with self.subTest(exit_code=code, cwd=cwd):
                argv = [sys.executable, "-c",
                        f"import sys; print('out'); print('err', file=sys.stderr); sys.exit({code})"]
                result = server.run_command(argv, cwd=cwd)
                self.assertEqual(result, {
                    "argv": argv, "cwd": str(self.workdir), "exit_code": code,
                    "stdout": "out\n", "stderr": "err\n",
                    "timed_out": False, "truncated": False,
                })

    def test_timeout_preserves_partial_output_and_truncation(self) -> None:
        argv = [sys.executable, "-c",
                "import os, time; os.write(1, '가나다라마바사아자차'.encode()); "
                "os.write(2, b'\\xff'); time.sleep(60)"]
        with patch.object(server, "MAX_COMMAND_OUTPUT", 8):
            result = server.run_command(argv, timeout_seconds=1)
        self.assertIsNone(result["exit_code"])
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["stdout"], "가나다라마바사아\n...[truncated]")
        self.assertEqual(result["stderr"], "\ufffd")


class MCPStartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.env = {
            # These tests only talk to loopback, regardless of the host proxy.
            **{key: value for key, value in os.environ.items()
               if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}},
            "AGENT_WORKDIR": self.temp.name,
            "MCP_HOST": "127.0.0.1",
            "MCP_PORT": str(self.port),
            "MCP_URL": f"http://127.0.0.1:{self.port}/mcp",
        }

    def start_server(self, *, delay: float = 0, legacy: bool = False) -> None:
        code = """
import sys, time
time.sleep(float(sys.argv[1]))
import server
if sys.argv[2] == "legacy":
    @server.mcp.tool()
    def legacy_tool() -> str:
        return "old tool"
server.main()
"""
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(delay), "legacy" if legacy else "current"],
            cwd=ROOT, env=self.env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def stop() -> None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        self.addCleanup(stop)

    def probe(self, seconds: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "smoke_test.py"), "--wait-seconds", str(seconds)],
            cwd=ROOT, env=self.env, capture_output=True, text=True,
            timeout=seconds + 10,
        )

    def test_delayed_listener_becomes_ready(self) -> None:
        self.start_server(delay=2)
        result = self.probe(10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Tools: run_command\n", result.stdout)

    def test_legacy_tool_list_fails_without_success_output(self) -> None:
        self.start_server(legacy=True)
        result = self.probe(3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected MCP tools", result.stderr)
        self.assertIn("legacy_tool", result.stderr)
        self.assertNotIn("Tools:", result.stdout)
        self.assertNotIn("Connected to", result.stdout)

    def test_missing_listener_has_bounded_wait(self) -> None:
        started = time.monotonic()
        result = self.probe(0.2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MCP did not become ready within 0.2 seconds", result.stderr)
        self.assertLess(time.monotonic() - started, 5)


class ProbeTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_unresponsive_probe_has_bounded_wait(self) -> None:
        async def hang(_url: str) -> None:
            await asyncio.sleep(60)

        with patch.object(smoke_test, "check_mcp", side_effect=hang):
            with self.assertRaisesRegex(RuntimeError, "within 0.1 seconds"):
                await asyncio.wait_for(smoke_test.main(0.1), timeout=2)


class BootstrapRestartTests(unittest.TestCase):
    def run_startup(self, *, fail_mcp: bool = False) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        # Exercise the real bootstrap startup section with fake host services.
        # Package installation and /etc writes must never run in these tests.
        source = (ROOT / "bootstrap.sh").read_text()
        startup = source[source.index('log "Starting root management agent"'):]
        preamble = r'''
set -Eeuo pipefail
log() { printf '%s\n' "$*"; }
die() { printf '%s\n' "$*" >&2; exit 1; }
HEALTH_URL=http://127.0.0.1:8080
MCP_URL=http://127.0.0.1:8000/mcp
AGENT_WORKDIR=/test
TUNNEL_ID=test-id
systemctl() {
  printf 'systemctl %s\n' "$*" >>"$CALL_LOG"
  if [[ "$*" == 'restart chat-bridge-oci.service' && "$FAIL_MCP" == 1 ]]; then
    printf 'Tools: legacy_tool, run_command\n'
    return 1
  fi
  case "$1" in
    is-active) printf 'active\n' ;;
    is-enabled) printf 'enabled\n' ;;
  esac
  return 0
}
curl() { printf 'curl\n' >>"$CALL_LOG"; }
journalctl() { return 0; }
'''
        with tempfile.TemporaryDirectory() as temp:
            calls = Path(temp) / "calls"
            result = subprocess.run(
                ["bash", "-c", preamble + startup], capture_output=True, text=True,
                env={**os.environ, "CALL_LOG": str(calls), "FAIL_MCP": str(int(fail_mcp))},
                timeout=5,
            )
            return result, calls.read_text().splitlines()

    def test_reinstall_restarts_both_services_in_order(self) -> None:
        result, calls = self.run_startup()
        self.assertEqual(result.returncode, 0, result.stderr)
        stop = calls.index("systemctl stop chat-bridge-oci-tunnel.service")
        mcp = calls.index("systemctl restart chat-bridge-oci.service")
        tunnel = calls.index("systemctl restart chat-bridge-oci-tunnel.service")
        self.assertLess(stop, mcp)
        self.assertLess(mcp, tunnel)
        self.assertLess(tunnel, calls.index("curl"))

    def test_failed_mcp_start_never_starts_tunnel(self) -> None:
        result, calls = self.run_startup(fail_mcp=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MCP service startup or smoke test failed", result.stderr)
        self.assertNotIn("systemctl restart chat-bridge-oci-tunnel.service", calls)
        self.assertNotIn("curl", calls)


if __name__ == "__main__":
    unittest.main()
