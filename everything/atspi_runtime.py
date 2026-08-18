from __future__ import annotations

import asyncio
import json
import os
import select
import signal
import sys
from dataclasses import dataclass
from typing import Protocol


class StatusBackend(Protocol):
    def get(self, name: str) -> bool: ...

    def set(self, name: str, value: bool) -> None: ...


class GioStatusBackend:
    def __init__(self) -> None:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        self.Gio = Gio
        self.GLib = GLib
        self.proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.a11y.Bus",
            "/org/a11y/bus",
            "org.freedesktop.DBus.Properties",
            None,
        )

    def get(self, name: str) -> bool:
        result = self.proxy.call_sync(
            "Get",
            self.GLib.Variant("(ss)", ("org.a11y.Status", name)),
            self.Gio.DBusCallFlags.NONE,
            1500,
            None,
        )
        unpacked = result.unpack()[0]
        if hasattr(unpacked, "unpack"):
            unpacked = unpacked.unpack()
        return bool(unpacked)

    def set(self, name: str, value: bool) -> None:
        self.proxy.call_sync(
            "Set",
            self.GLib.Variant(
                "(ssv)",
                ("org.a11y.Status", name, self.GLib.Variant("b", bool(value))),
            ),
            self.Gio.DBusCallFlags.NONE,
            1500,
            None,
        )


@dataclass(slots=True)
class AtspiRuntimeLease:
    """Temporarily enables AT-SPI, never screen-reader mode."""

    backend: StatusBackend
    original_enabled: bool | None = None
    original_screen_reader: bool | None = None
    changed: bool = False

    def acquire(self) -> None:
        if self.original_enabled is not None:
            return
        self.original_enabled = self.backend.get("IsEnabled")
        self.original_screen_reader = self.backend.get("ScreenReaderEnabled")
        if not self.original_enabled:
            self.backend.set("IsEnabled", True)
            self.changed = True

    def restore(self) -> None:
        if self.original_enabled is None:
            return
        try:
            if self.changed:
                self.backend.set("IsEnabled", self.original_enabled)
            # Everything never writes ScreenReaderEnabled. If an external
            # actor changed it while the panel was open, leave that choice
            # alone rather than racing it during restoration.
        finally:
            self.original_enabled = None
            self.original_screen_reader = None
            self.changed = False


def run_guard(parent_pid: int) -> int:
    """Own the runtime flag so pipe EOF restores it even if the helper dies."""

    lease: AtspiRuntimeLease | None = None
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        lease = AtspiRuntimeLease(GioStatusBackend())
        lease.acquire()
        print(
            json.dumps(
                {
                    "ok": True,
                    "changed": lease.changed,
                    "enabledBefore": lease.original_enabled,
                    "screenReaderBefore": lease.original_screen_reader,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    except Exception as error:  # D-Bus absence is a provider failure, not fatal.
        print(json.dumps({"ok": False, "error": str(error)}, separators=(",", ":")), flush=True)
        return 1

    try:
        descriptor = sys.stdin.fileno()
        while not stopping:
            if os.getppid() != parent_pid:
                break
            readable, _, _ = select.select([descriptor], [], [], 0.5)
            if not readable:
                continue
            data = os.read(descriptor, 4096)
            if not data or b"stop" in data:
                break
    finally:
        if lease:
            lease.restore()
    return 0


class AtspiGuardClient:
    def __init__(self, helper_path: str) -> None:
        self.helper_path = helper_path
        self.process: asyncio.subprocess.Process | None = None
        self.warning = ""

    async def start(self) -> bool:
        if self.process and self.process.returncode is None:
            return True
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            self.helper_path,
            "--atspi-guard",
            str(os.getpid()),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), 3.0)  # type: ignore[union-attr]
            status = json.loads(line)
        except (TimeoutError, json.JSONDecodeError, TypeError) as error:
            self.warning = f"AT-SPI runtime guard did not start: {error}"
            await self.stop()
            return False
        if not isinstance(status, dict) or status.get("ok") is not True:
            self.warning = "AT-SPI unavailable: " + str(status.get("error") or "unknown error")
            await self.stop()
            return False
        return True

    async def stop(self) -> None:
        process = self.process
        self.process = None
        if not process or process.returncode is not None:
            return
        if process.stdin:
            try:
                process.stdin.write(b"stop\n")
                await process.stdin.drain()
                process.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass
        try:
            await asyncio.wait_for(process.wait(), 2.0)
        except TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 1.0)
            except TimeoutError:
                process.kill()
                await process.wait()

