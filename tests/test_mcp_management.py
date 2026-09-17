"""MCP 管理接口的配置更新与敏感字段保留回归。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from harness.routes.mcp import MCPServerPatch, update_server
from harness.tools.mcp import _INITIALIZE_TIMEOUT, MCPClient


class MCPClientStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_uses_cold_start_timeout(self) -> None:
        process = SimpleNamespace(stdin=object(), stdout=object(), stderr=None)
        request = AsyncMock(return_value={})
        notify = AsyncMock()
        client = MCPClient("everything", "npx", ["server-everything"])

        with patch(
            "harness.tools.mcp.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ), patch.object(client, "_request", new=request), patch.object(
            client, "_notify", new=notify
        ):
            await client.start()

        self.assertEqual(request.await_args.kwargs["response_timeout"], _INITIALIZE_TIMEOUT)
        notify.assert_awaited_once_with("notifications/initialized")


class MCPServerUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_preserves_existing_env_when_omitted(self) -> None:
        existing = {
            "name": "filesystem",
            "command": "old-command",
            "args": ["old-arg"],
            "env": {"SECRET_TOKEN": "secret-value"},
            "enabled": True,
        }
        unmount = AsyncMock(return_value=[])
        mount = AsyncMock(return_value={})
        with patch("harness.routes.mcp._persisted_specs", return_value=[existing]), patch(
            "harness.routes.mcp._save_servers"
        ) as save, patch("harness.routes.mcp.unmount_mcp_server", new=unmount), patch(
            "harness.routes.mcp.mount_mcp_server", new=mount
        ), patch("harness.routes.mcp.snapshot_mcp_servers", return_value={}):
            result = await update_server(
                "filesystem",
                MCPServerPatch(command="new-command", args=["new-arg"], confirm=True),
                {},
            )

        saved = save.call_args.args[0][0]
        self.assertEqual(saved["env"], {"SECRET_TOKEN": "secret-value"})
        self.assertEqual(result.env_keys, ["SECRET_TOKEN"])
        unmount.assert_awaited_once_with("filesystem", drain=True)
        mount.assert_awaited_once_with(saved)

    async def test_explicit_empty_env_clears_secret_and_disable_does_not_remount(self) -> None:
        existing = {
            "name": "filesystem",
            "command": "server",
            "env": {"SECRET_TOKEN": "secret-value"},
            "enabled": True,
        }
        unmount = AsyncMock(return_value=[])
        mount = AsyncMock(return_value={})
        with patch("harness.routes.mcp._persisted_specs", return_value=[existing]), patch(
            "harness.routes.mcp._save_servers"
        ) as save, patch("harness.routes.mcp.unmount_mcp_server", new=unmount), patch(
            "harness.routes.mcp.mount_mcp_server", new=mount
        ), patch("harness.routes.mcp.snapshot_mcp_servers", return_value={}):
            result = await update_server(
                "filesystem",
                MCPServerPatch(env={}, enabled=False, confirm=True),
                {},
            )

        saved = save.call_args.args[0][0]
        self.assertEqual(saved["env"], {})
        self.assertFalse(result.enabled)
        unmount.assert_awaited_once_with("filesystem", drain=True)
        mount.assert_not_awaited()

    async def test_update_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await update_server("filesystem", MCPServerPatch(command="server"), {})
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
