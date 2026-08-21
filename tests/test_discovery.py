from __future__ import annotations

import asyncio
import threading
import unittest

from everything.atspi_runtime import AtspiExecutor
from everything.discovery import DiscoveryManager
from everything.model import Thing
from everything.providers.base import ProviderResult


def thing(provider: str, identifier: str) -> Thing:
    return Thing(
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


class BlockingAtspiProvider:
    name = "atspi"

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.thread_id: int | None = None

    async def scan(self, _context):
        self.thread_id = threading.get_ident()
        self.started.set()
        self.release.wait(2.0)
        return ProviderResult(self.name)


class RecordingNativeProvider:
    def __init__(self, name: str, observed: list[tuple[str, int]]) -> None:
        self.name = name
        self.observed = observed

    async def scan(self, _context):
        self.observed.append((self.name, threading.get_ident()))
        await asyncio.sleep(0)
        return ProviderResult(self.name)


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_results_and_failures_are_isolated(self) -> None:
        messages: list[dict] = []

        async def emit(message: dict) -> None:
            messages.append(message)

        manager = DiscoveryManager(emit, atspi_available=False)
        manager.providers = {
            "hyprland": StaticProvider(
                "hyprland",
                ProviderResult("hyprland", [thing("hyprland", "outer")]),
            ),
            "kitty": StaticProvider(
                "kitty", ProviderResult("kitty", [thing("kitty", "pane")])
            ),
            "tmux": StaticProvider("tmux", error=RuntimeError("socket changed")),
        }
        manager.registry.publish("tmux", [thing("tmux", "old")])

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

    async def test_blocking_atspi_scan_does_not_starve_or_delay_protocol_cancellation(self) -> None:
        messages: list[dict] = []

        async def emit(message: dict) -> None:
            messages.append(message)

        blocking = BlockingAtspiProvider()
        manager = DiscoveryManager(emit, atspi_available=False)
        manager.atspi_executor = AtspiExecutor()
        manager.providers = {
            "hyprland": StaticProvider("hyprland", ProviderResult("hyprland")),
            "atspi": blocking,
        }
        task = asyncio.create_task(manager.scan("blocked", include_ghostty=False))
        try:
            started = await asyncio.to_thread(blocking.started.wait, 1.0)
            self.assertTrue(started)
            self.assertNotEqual(blocking.thread_id, threading.get_ident())

            # The protocol loop can still run callbacks while the owner thread
            # is synchronously occupied by a slow accessibility peer.
            heartbeat = asyncio.Event()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            await asyncio.wait_for(heartbeat.wait(), 0.2)

            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.2)
            self.assertFalse(blocking.release.is_set())
            self.assertEqual(messages[0]["provider"], "hyprland")
        finally:
            blocking.release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await manager.close()

    async def test_atspi_and_ghostty_share_the_dedicated_owner_thread(self) -> None:
        async def emit(_message: dict) -> None:
            return None

        observed: list[tuple[str, int]] = []
        manager = DiscoveryManager(emit, atspi_available=False)
        manager.atspi_executor = AtspiExecutor()
        manager.providers = {
            "atspi": RecordingNativeProvider("atspi", observed),
            "ghostty": RecordingNativeProvider("ghostty", observed),
        }
        owner_thread = manager.atspi_executor.thread_id
        context = manager.context()
        try:
            await asyncio.gather(
                manager._scan_provider("atspi", context),
                manager._scan_provider("ghostty", context),
            )
        finally:
            await manager.close()

        self.assertEqual({name for name, _thread in observed}, {"atspi", "ghostty"})
        self.assertEqual({thread for _name, thread in observed}, {owner_thread})
        self.assertNotEqual(owner_thread, threading.get_ident())


if __name__ == "__main__":
    unittest.main()
