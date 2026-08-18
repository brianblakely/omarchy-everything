from __future__ import annotations

import asyncio
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from ..commands import CommandError
from ..model import Viewport, process_birth, stable_id
from ..processes import canonical_path
from .base import ProviderResult, ScanContext, normalized_address
from .hyprland import focus_address


SOCKET_NAME = re.compile(r"^omarchy-kitty-(\d+)$")


class KittyProvider:
    name = "kitty"

    @staticmethod
    def sockets(context: ScanContext) -> list[tuple[str, int, str, int, int]]:
        runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        out: list[tuple[str, int, str, int, int]] = []
        try:
            entries = list(os.scandir(runtime))
        except OSError:
            return out
        for entry in entries:
            match = SOCKET_NAME.fullmatch(entry.name)
            if not match:
                continue
            pid = int(match.group(1))
            process = context.processes.get(pid)
            try:
                info = os.stat(entry.path, follow_symlinks=False)
            except OSError:
                continue
            if (
                info.st_uid != os.getuid()
                or not stat.S_ISSOCK(info.st_mode)
                or not process
                or "kitty" not in (process.comm + " " + " ".join(process.argv)).lower()
            ):
                continue
            out.append((entry.path, pid, process.start_time, info.st_dev, info.st_ino))
        return sorted(out)

    async def scan(self, context: ScanContext) -> ProviderResult:
        items: list[Viewport] = []
        warnings: list[str] = []
        surfaces: list[dict[str, Any]] = []
        for socket_path, pid, birth, socket_dev, socket_ino in self.sockets(context):
            result = await context.runner.run(
                ["kitten", "@", "--to", "unix:" + socket_path, "ls"], timeout=1.2
            )
            if result.returncode != 0:
                warnings.append(f"Kitty socket {Path(socket_path).name} is stale")
                continue
            try:
                os_windows = json.loads(result.stdout)
            except json.JSONDecodeError:
                warnings.append(f"Kitty socket {Path(socket_path).name} returned invalid data")
                continue
            if not isinstance(os_windows, list):
                continue
            for os_window in os_windows:
                if not isinstance(os_window, dict):
                    continue
                os_id = int(os_window.get("id") or 0)
                tabs = [tab for tab in os_window.get("tabs", []) if isinstance(tab, dict)]
                host = self._match_host(context, pid, tabs)
                parent_window = self._parent_window_id(context, host)
                host_address = normalized_address(host.get("address")) if host else ""
                for tab in tabs:
                    tab_id = int(tab.get("id") or 0)
                    if tab_id <= 0:
                        continue
                    tab_title = str(tab.get("title") or "Kitty tab")
                    windows = [window for window in tab.get("windows", []) if isinstance(window, dict)]
                    if not tab_title and windows:
                        tab_title = str(windows[0].get("title") or "Kitty tab")
                    tab_viewport_id = stable_id(
                        self.name,
                        socket_path,
                        socket_dev,
                        socket_ino,
                        pid,
                        birth,
                        os_id,
                        "tab",
                        tab_id,
                    )
                    tab_active = bool(os_window.get("is_focused") and tab.get("is_focused"))
                    items.append(
                        Viewport(
                            id=tab_viewport_id,
                            kind="terminal-tab",
                            provider="Kitty",
                            title=tab_title,
                            context=self._tab_context(windows),
                            search_terms=["kitty", self._tab_context(windows)],
                            parent_id=parent_window,
                            badges=["Tab"],
                            active=tab_active,
                            recency=3500 if tab_active else 0,
                            activation={
                                "socket": socket_path,
                                "socket_dev": socket_dev,
                                "socket_ino": socket_ino,
                                "pid": pid,
                                "birth": birth,
                                "os_window_id": os_id,
                                "tab_id": tab_id,
                                "address": host_address,
                                "target": "tab",
                            },
                        )
                    )
                    for window in windows:
                        window_id = int(window.get("id") or 0)
                        if window_id <= 0:
                            continue
                        cwd = canonical_path(str(window.get("cwd") or ""))
                        title = str(window.get("title") or tab_title or "Kitty pane")
                        active = tab_active and bool(window.get("is_focused"))
                        pane_id = stable_id(
                            self.name,
                            socket_path,
                            socket_dev,
                            socket_ino,
                            pid,
                            birth,
                            os_id,
                            "pane",
                            window_id,
                        )
                        items.append(
                            Viewport(
                                id=pane_id,
                                kind="terminal-pane",
                                provider="Kitty",
                                title=title,
                                context=cwd or tab_title,
                                search_terms=["kitty", cwd, tab_title],
                                parent_id=tab_viewport_id,
                                badges=["Pane"],
                                active=active,
                                recency=3800 if active else 0,
                                activation={
                                    "socket": socket_path,
                                    "socket_dev": socket_dev,
                                    "socket_ino": socket_ino,
                                    "pid": pid,
                                    "birth": birth,
                                    "os_window_id": os_id,
                                    "window_id": window_id,
                                    "address": host_address,
                                    "target": "window",
                                },
                            )
                        )
                        surfaces.append(
                            {
                                "provider": self.name,
                                "item_id": pane_id,
                                "pid": pid,
                                "title": title,
                                "cwd": cwd,
                                "address": host_address,
                                "window_id": window_id,
                                "activation": {
                                    "socket": socket_path,
                                    "socket_dev": socket_dev,
                                    "socket_ino": socket_ino,
                                    "pid": pid,
                                    "birth": birth,
                                    "os_window_id": os_id,
                                    "window_id": window_id,
                                    "address": host_address,
                                    "target": "window",
                                },
                            }
                        )
        return ProviderResult(self.name, items, warnings, {"surfaces": surfaces})

    @staticmethod
    def _tab_context(windows: list[dict[str, Any]]) -> str:
        paths = [canonical_path(str(window.get("cwd") or "")) for window in windows]
        paths = [path for path in paths if path]
        return paths[0] if paths and all(path == paths[0] for path in paths) else "Kitty"

    @staticmethod
    def _match_host(
        context: ScanContext, pid: int, tabs: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        clients = context.clients_for_pid(pid)
        if len(clients) == 1:
            return clients[0]
        focused_tab = next((tab for tab in tabs if tab.get("is_focused")), tabs[0] if tabs else {})
        title = str(focused_tab.get("title") or "")
        matches = [client for client in clients if str(client.get("title") or "") == title]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _parent_window_id(context: ScanContext, client: dict[str, Any] | None) -> str:
        if not client:
            return ""
        address = normalized_address(client.get("address"))
        for metadata in context.provider_metadata.get("hyprland", {}).get("clients", []):
            if normalized_address(metadata.get("address")) == address:
                return str(metadata.get("item_id") or "")
        return ""

    async def activate(self, activation: dict[str, Any], context: ScanContext) -> None:
        socket_path = str(activation.get("socket") or "")
        pid = int(activation.get("pid") or 0)
        if process_birth(pid) != str(activation.get("birth")):
            raise CommandError("Kitty process was replaced")
        try:
            info = os.stat(socket_path, follow_symlinks=False)
        except OSError as error:
            raise CommandError("Kitty socket closed") from error
        if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
            raise CommandError("Kitty socket is not a current user socket")
        if (
            int(activation.get("socket_dev") or 0) != info.st_dev
            or int(activation.get("socket_ino") or 0) != info.st_ino
        ):
            raise CommandError("Kitty socket was replaced")

        target = str(activation.get("target") or "")
        if target == "tab":
            identifier = int(activation.get("tab_id") or 0)
            command = "focus-tab"
        elif target == "window":
            identifier = int(activation.get("window_id") or 0)
            command = "focus-window"
        else:
            raise CommandError("unknown Kitty activation target")
        if identifier <= 0:
            raise CommandError("invalid Kitty target id")
        result = await context.runner.run(
            [
                "kitten",
                "@",
                "--to",
                "unix:" + socket_path,
                command,
                "--match",
                f"id:{identifier}",
            ],
            timeout=1.2,
        )
        if result.returncode != 0:
            raise CommandError(result.stderr.strip() or "Kitty target is stale")

        address = normalized_address(activation.get("address"))
        client = context.client_by_address(address) if address else None
        if not client or int(client.get("pid") or 0) != pid:
            address = await self._focused_address_for_pid(context, pid)
        if not address:
            raise CommandError("Kitty focused its pane but its managed window could not be identified")
        await focus_address(context, address)

    @staticmethod
    async def _focused_address_for_pid(context: ScanContext, pid: int) -> str:
        for _attempt in range(8):
            result = await context.runner.run(["hyprctl", "-j", "activewindow"], timeout=0.5)
            if result.returncode == 0:
                try:
                    active = json.loads(result.stdout)
                except json.JSONDecodeError:
                    active = {}
                if isinstance(active, dict) and int(active.get("pid") or 0) == pid:
                    return normalized_address(active.get("address"))
            await asyncio.sleep(0.04)
        return ""
