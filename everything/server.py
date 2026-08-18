from __future__ import annotations

import asyncio
import json
import signal
import sys
from typing import Any

from . import PLUGIN_VERSION, PROTOCOL_VERSION
from .atspi_runtime import AtspiGuardClient
from .discovery import DiscoveryManager


class JsonLineServer:
    def __init__(self, helper_path: str, *, test_mode: bool = False) -> None:
        self.helper_path = helper_path
        self.test_mode = test_mode
        self.guard = AtspiGuardClient(helper_path)
        self.manager: DiscoveryManager | None = None
        self.scan_task: asyncio.Task[None] | None = None
        self.activation_tasks: set[asyncio.Task[None]] = set()
        self.stopping = False
        self.event_pending = False
        self.event_timer: asyncio.TimerHandle | None = None
        self.output_lock = asyncio.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def emit(self, message: dict[str, Any]) -> None:
        async with self.output_lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    async def run(self) -> int:
        self.loop = asyncio.get_running_loop()
        atspi_available = True
        guard_warning = ""
        if not self.test_mode:
            atspi_available = await self.guard.start()
            guard_warning = self.guard.warning
        self.manager = DiscoveryManager(
            self.emit,
            atspi_available=atspi_available,
            test_mode=self.test_mode,
        )
        if guard_warning:
            self.manager.warnings["atspi-runtime"] = [guard_warning]
        if atspi_available and not self.test_mode:
            self.manager.start_events(self._event_from_thread)

        await self.emit(
            {
                "version": PROTOCOL_VERSION,
                "type": "ready",
                "pluginVersion": PLUGIN_VERSION,
                "capabilities": {
                    "partialSnapshots": True,
                    "atspi": atspi_available,
                    "ghosttyPalette": atspi_available,
                },
            }
        )

        stop_event = asyncio.Event()

        def stop() -> None:
            self.stopping = True
            stop_event.set()

        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                self.loop.add_signal_handler(signum, stop)
            except NotImplementedError:
                pass

        reader_task = asyncio.create_task(self._read_loop(stop_event), name="json-lines-reader")
        reader_task.add_done_callback(lambda _task: stop_event.set())
        await stop_event.wait()
        self.stopping = True
        reader_task.cancel()
        await asyncio.gather(reader_task, return_exceptions=True)
        await self._cancel_work()
        if self.manager:
            self.manager.stop_events()
        await self.guard.stop()
        return 0

    async def _read_loop(self, stop_event: asyncio.Event) -> None:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
        try:
            while not self.stopping:
                line = await reader.readline()
                if not line:
                    stop_event.set()
                    return
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    await self._protocol_error("", "Malformed JSON request")
                    continue
                if not isinstance(message, dict):
                    await self._protocol_error("", "Request must be a JSON object")
                    continue
                request_id = str(message.get("id") or "")
                if message.get("version") != PROTOCOL_VERSION or not request_id:
                    await self._protocol_error(request_id, "Unsupported protocol version or missing request id")
                    continue
                request_type = str(message.get("type") or "")
                if request_type == "scan":
                    options = message.get("options") if isinstance(message.get("options"), dict) else {}
                    await self._start_scan(request_id, bool(options.get("ghostty")))
                elif request_type == "activate":
                    item_id = str(message.get("itemId") or "")
                    token = str(message.get("token") or "")
                    if not item_id or not token:
                        await self._protocol_error(request_id, "Activation requires itemId and token")
                        continue
                    assert self.manager is not None
                    task = asyncio.create_task(
                        self.manager.activate(request_id, item_id, token), name=f"activate:{request_id}"
                    )
                    self.activation_tasks.add(task)
                    task.add_done_callback(self.activation_tasks.discard)
                elif request_type == "shutdown":
                    stop_event.set()
                    return
                else:
                    await self._protocol_error(request_id, f"Unknown request type: {request_type}")
        finally:
            transport.close()

    async def _start_scan(self, request_id: str, include_ghostty: bool) -> None:
        if self.scan_task and not self.scan_task.done():
            self.scan_task.cancel()
            await asyncio.gather(self.scan_task, return_exceptions=True)
        assert self.manager is not None
        self.scan_task = asyncio.create_task(
            self.manager.scan(request_id, include_ghostty=include_ghostty), name=f"scan:{request_id}"
        )

    def _event_from_thread(self) -> None:
        if not self.loop or self.stopping:
            return
        self.loop.call_soon_threadsafe(self._debounce_event_scan)

    def _debounce_event_scan(self) -> None:
        if self.stopping:
            return
        self.event_pending = True
        if self.event_timer:
            self.event_timer.cancel()
        self.event_timer = self.loop.call_later(0.25, self._start_event_scan) if self.loop else None

    def _start_event_scan(self) -> None:
        self.event_timer = None
        if self.stopping or not self.event_pending:
            return
        if self.scan_task and not self.scan_task.done():
            if self.loop:
                self.event_timer = self.loop.call_later(0.35, self._start_event_scan)
            return
        self.event_pending = False
        assert self.manager is not None
        self.scan_task = asyncio.create_task(
            self.manager.scan("event", include_ghostty=False), name="scan:event"
        )

    async def _protocol_error(self, request_id: str, message: str) -> None:
        await self.emit(
            {
                "version": PROTOCOL_VERSION,
                "type": "error",
                "requestId": request_id,
                "message": message,
                "nonfatal": True,
            }
        )

    async def _cancel_work(self) -> None:
        tasks: list[asyncio.Task[Any]] = []
        if self.scan_task and not self.scan_task.done():
            self.scan_task.cancel()
            tasks.append(self.scan_task)
        for task in self.activation_tasks:
            if not task.done():
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.event_timer:
            self.event_timer.cancel()
            self.event_timer = None
