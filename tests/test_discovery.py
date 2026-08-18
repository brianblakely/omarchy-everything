from __future__ import annotations

import asyncio
import unittest

from everything.discovery import DiscoveryManager
from everything.model import Viewport
from everything.providers.base import ProviderResult


def viewport(provider: str, identifier: str) -> Viewport:
    return Viewport(
        id=f"{provider}:{identifier}",
        kind="window",
        provider=provider.title(),
        title=identifier,
        activation={"native": identifier},
    )


class StaticProvider:
    def __init__(self, name: str, result: ProviderResult | None = None, error: Exception | None = None):
        self.name = name
        self.result = result or ProviderResult(name)
        self.error = error

    async def scan(self, _context):
        if self.error:
            raise self.error
        return self.result


class SlowProvider:
    name = "kitty"

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def scan(self, _context):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_results_and_failures_are_isolated(self) -> None:
        messages: list[dict] = []

        async def emit(message: dict) -> None:
            messages.append(message)

        manager = DiscoveryManager(emit, atspi_available=False)
        manager.providers = {
            "hyprland": StaticProvider(
                "hyprland",
                ProviderResult("hyprland", [viewport("hyprland", "outer")]),
            ),
            "kitty": StaticProvider(
                "kitty", ProviderResult("kitty", [viewport("kitty", "pane")])
            ),
            "tmux": StaticProvider("tmux", error=RuntimeError("socket changed")),
        }
        manager.registry.publish("tmux", [viewport("tmux", "old")])

        await manager.scan("scan-1", include_ghostty=False)

        partials = [message for message in messages if message.get("type") == "snapshot" and not message["full"]]
        self.assertEqual(partials[0]["provider"], "hyprland", "managed windows publish first")
        self.assertIn("kitty", {message["provider"] for message in partials})
        tmux_partial = next(message for message in partials if message["provider"] == "tmux")
        self.assertEqual(tmux_partial["items"], [], "failed providers drop stale internal rows")
        error = next(message for message in messages if message.get("type") == "error")
        self.assertTrue(error["nonfatal"])
        full = [message for message in messages if message.get("full") is True][-1]
        self.assertEqual(full["requestId"], "scan-1")
        self.assertEqual({row["id"] for row in full["items"]}, {"hyprland:outer", "kitty:pane"})

    async def test_scan_cancellation_reaches_provider_tasks(self) -> None:
        async def emit(_message: dict) -> None:
            return None

        slow = SlowProvider()
        manager = DiscoveryManager(emit, atspi_available=False)
        manager.providers = {
            "hyprland": StaticProvider("hyprland", ProviderResult("hyprland")),
            "kitty": slow,
        }
        task = asyncio.create_task(manager.scan("cancelled", include_ghostty=False))
        await asyncio.wait_for(slow.started.wait(), 1.0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(slow.cancelled)


if __name__ == "__main__":
    unittest.main()
