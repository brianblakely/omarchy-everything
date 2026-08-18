from __future__ import annotations

import os
import re
import stat
import time
from pathlib import Path
from typing import Any

from ..commands import CommandError
from ..model import Viewport, process_birth, stable_id
from ..processes import canonical_path
from .base import ProviderResult, ScanContext, route_for_process
from .hyprland import launch_terminal_and_focus


SEP = "\x1f"
NATIVE_ID = re.compile(r"^[\$@%][0-9]+$")


class TmuxProvider:
    name = "tmux"

    def discover_sockets(self, context: ScanContext) -> list[str]:
        candidates: set[str] = set()
        default_dir = f"/tmp/tmux-{os.getuid()}"
        try:
            for entry in os.scandir(default_dir):
                candidates.add(entry.path)
        except OSError:
            pass
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime:
            try:
                for entry in os.scandir(runtime):
                    if "tmux" in entry.name.lower():
                        candidates.add(entry.path)
            except OSError:
                pass
        for process in context.processes.named("tmux"):
            argv = list(process.argv)
            for index, argument in enumerate(argv[:-1]):
                if argument == "-S":
                    candidates.add(os.path.abspath(os.path.expanduser(argv[index + 1])))
        valid: list[str] = []
        for candidate in candidates:
            try:
                info = os.stat(candidate, follow_symlinks=False)
            except OSError:
                continue
            if info.st_uid == os.getuid() and stat.S_ISSOCK(info.st_mode):
                valid.append(os.path.realpath(candidate))
        return sorted(set(valid))

    async def _records(self, context: ScanContext, socket: str, command: list[str], fields: list[str]) -> list[list[str]]:
        format_string = SEP.join(f"#{{{field}}}" for field in fields)
        result = await context.runner.run(["tmux", "-S", socket, *command, "-F", format_string], timeout=1.0)
        if result.returncode != 0:
            raise CommandError(result.stderr.strip() or "tmux query failed")
        rows: list[list[str]] = []
        for line in result.stdout.splitlines():
            parts = line.split(SEP)
            if len(parts) == len(fields):
                rows.append(parts)
        return rows

    async def scan(self, context: ScanContext) -> ProviderResult:
        items: list[Viewport] = []
        warnings: list[str] = []
        panes_meta: list[dict[str, Any]] = []
        sockets_meta: list[dict[str, Any]] = []
        now = time.time()

        def recent(value: str, bonus: float = 0) -> float:
            try:
                age = max(0.0, now - float(value or 0))
            except ValueError:
                age = 1000.0
            return bonus + max(0.0, 1000.0 - min(1000.0, age))

        for socket in self.discover_sockets(context):
            try:
                sessions = await self._records(
                    context,
                    socket,
                    ["list-sessions"],
                    ["pid", "session_id", "session_name", "session_attached", "session_activity"],
                )
                windows = await self._records(
                    context,
                    socket,
                    ["list-windows", "-a"],
                    ["session_id", "window_id", "window_name", "window_active", "window_activity"],
                )
                panes = await self._records(
                    context,
                    socket,
                    ["list-panes", "-a"],
                    [
                        "session_id",
                        "window_id",
                        "pane_id",
                        "pane_title",
                        "pane_current_path",
                        "pane_active",
                        "pane_pid",
                    ],
                )
                clients = await self._records(
                    context,
                    socket,
                    ["list-clients"],
                    ["client_name", "client_pid", "client_session", "client_tty"],
                )
            except CommandError as error:
                warnings.append(f"tmux socket {Path(socket).name}: {error}")
                continue
            server_pid = int(sessions[0][0]) if sessions else 0
            birth = process_birth(server_pid)
            session_ids: dict[str, str] = {}
            window_ids: dict[str, str] = {}
            for _pid, native_id, name, attached, activity in sessions:
                if not NATIVE_ID.fullmatch(native_id):
                    continue
                item_id = stable_id(self.name, socket, server_pid, birth, native_id)
                session_ids[native_id] = item_id
                items.append(
                    Viewport(
                        id=item_id,
                        kind="tmux-session",
                        provider="tmux",
                        title=name or native_id,
                        context=f"{attached} attached client" + ("s" if attached != "1" else ""),
                        search_terms=["tmux", socket, native_id],
                        badges=["Session", "Attached" if attached != "0" else "Detached"],
                        recency=recent(activity),
                        activation=self._activation(socket, server_pid, birth, native_id, "session", clients, native_id),
                    )
                )
            for session_id, native_id, name, active, activity in windows:
                if not NATIVE_ID.fullmatch(native_id):
                    continue
                item_id = stable_id(self.name, socket, server_pid, birth, native_id)
                window_ids[native_id] = item_id
                items.append(
                    Viewport(
                        id=item_id,
                        kind="tmux-window",
                        provider="tmux",
                        title=name or native_id,
                        context=f"tmux window {native_id}",
                        search_terms=["tmux", session_id, native_id],
                        parent_id=session_ids.get(session_id, ""),
                        badges=["Window"],
                        active=active == "1",
                        recency=recent(activity, 3000 if active == "1" else 0),
                        activation=self._activation(socket, server_pid, birth, native_id, "window", clients, session_id),
                    )
                )
            for session_id, window_id, native_id, title, cwd, active, pane_pid in panes:
                if not NATIVE_ID.fullmatch(native_id):
                    continue
                path = canonical_path(cwd)
                item_id = stable_id(self.name, socket, server_pid, birth, native_id)
                activation = self._activation(socket, server_pid, birth, native_id, "pane", clients, session_id)
                activation["pane_pid"] = int(pane_pid or 0)
                items.append(
                    Viewport(
                        id=item_id,
                        kind="tmux-pane",
                        provider="tmux",
                        title=title or Path(path).name or native_id,
                        context=path or f"tmux pane {native_id}",
                        search_terms=["tmux", session_id, window_id, native_id, path],
                        parent_id=window_ids.get(window_id, ""),
                        badges=["Pane"],
                        active=active == "1",
                        recency=3200 if active == "1" else 0,
                        activation=activation,
                    )
                )
                panes_meta.append(
                    {
                        "item_id": item_id,
                        "socket": socket,
                        "pane_id": native_id,
                        "pane_pid": int(pane_pid or 0),
                        "cwd": path,
                        "title": title,
                        "activation": activation,
                    }
                )
            sockets_meta.append({"socket": socket, "server_pid": server_pid, "birth": birth, "clients": clients})
        return ProviderResult(self.name, items, warnings, {"panes": panes_meta, "sockets": sockets_meta})

    @staticmethod
    def _activation(
        socket: str,
        server_pid: int,
        birth: str,
        target_id: str,
        target_kind: str,
        clients: list[list[str]],
        session_id: str,
    ) -> dict[str, Any]:
        return {
            "socket": socket,
            "server_pid": server_pid,
            "birth": birth,
            "target_id": target_id,
            "target_kind": target_kind,
            "session_id": session_id,
            "clients": clients,
        }

    async def activate(self, activation: dict[str, Any], context: ScanContext) -> None:
        socket = str(activation.get("socket") or "")
        server_pid = int(activation.get("server_pid") or 0)
        if process_birth(server_pid) != str(activation.get("birth")):
            raise CommandError("tmux server was replaced")
        try:
            info = os.stat(socket, follow_symlinks=False)
        except OSError as error:
            raise CommandError("tmux socket closed") from error
        if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
            raise CommandError("tmux socket is not owned by the current user")
        target = str(activation.get("target_id") or "")
        if not NATIVE_ID.fullmatch(target):
            raise CommandError("invalid tmux native target")

        live_clients = await self._records(
            context,
            socket,
            ["list-clients"],
            ["client_name", "client_pid", "client_session", "client_tty"],
        )
        routes = self._local_client_routes(context, live_clients)
        if len(routes) == 1:
            client_name, route = routes[0]
            result = await context.runner.run(
                ["tmux", "-S", socket, "switch-client", "-c", client_name, "-t", target], timeout=1.0
            )
            if result.returncode != 0:
                raise CommandError(result.stderr.strip() or "tmux target closed")
            provider_name = str(route.get("provider") or "")
            provider = context.providers.get(provider_name)
            if not provider:
                raise CommandError("tmux terminal route is unavailable")
            await provider.activate(dict(route.get("activation") or {}), context)
            return

        session_target = str(activation.get("session_id") or "")
        if not NATIVE_ID.fullmatch(session_target) or not session_target.startswith("$"):
            raise CommandError("tmux target has no live session")
        argv = ["omarchy-launch-terminal", "tmux", "-S", socket, "attach-session", "-t", session_target]
        if target.startswith("@"):
            argv.extend([";", "select-window", "-t", target])
        elif target.startswith("%"):
            argv.extend([";", "select-pane", "-t", target])
        await launch_terminal_and_focus(context, argv)

    @staticmethod
    def _local_client_routes(
        context: ScanContext, clients: list[Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        routes: list[tuple[str, dict[str, Any]]] = []
        for row in clients:
            if not isinstance(row, list) or len(row) < 2:
                continue
            try:
                pid = int(row[1])
            except ValueError:
                continue
            process = context.processes.get(pid)
            if not process or (
                process.comm.lower() != "tmux"
                and (not process.argv or os.path.basename(process.argv[0]).lower() != "tmux")
            ):
                continue
            route = route_for_process(context, pid, cwd=process.cwd)
            if route is not None:
                routes.append((str(row[0]), route))
        return routes
