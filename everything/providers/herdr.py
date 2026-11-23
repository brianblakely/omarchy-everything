from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from ..commands import CommandError, unix_json_request
from ..model import Thing, process_birth, stable_id
from ..processes import canonical_path
from .base import ProviderResult, ScanContext, normalized_address, route_for_process
from .hyprland import focus_address, launch_terminal_and_focus


class HerdrProvider:
    name = "herdr"

    async def scan(self, context: ScanContext) -> ProviderResult:
        listing = await context.runner.run(["herdr", "session", "list", "--json"], timeout=1.2)
        if listing.returncode != 0:
            raise CommandError(listing.stderr.strip() or "Herdr session discovery failed")
        try:
            sessions_value = json.loads(listing.stdout)
        except json.JSONDecodeError as error:
            raise CommandError("Herdr session list returned invalid JSON") from error
        sessions = sessions_value.get("sessions", []) if isinstance(sessions_value, dict) else []
        items: list[Thing] = []
        warnings: list[str] = []
        panes_metadata: list[dict[str, Any]] = []
        sessions_metadata: list[dict[str, Any]] = []

        for session in sessions:
            if not isinstance(session, dict) or session.get("running") is not True:
                continue
            name = str(session.get("name") or "default")
            socket_path = str(session.get("socket_path") or "")
            socket_info = self._validate_socket(socket_path)
            if not socket_info:
                warnings.append(f"Herdr session {name} has no safe local socket")
                continue
            server_pid = self._server_pid_for_socket(socket_path, context)
            birth = process_birth(server_pid) if server_pid else f"socket-{socket_info.st_ino}"
            try:
                response = await unix_json_request(
                    socket_path,
                    {"id": "everything:snapshot", "method": "session.snapshot", "params": {}},
                    timeout=1.1,
                )
                snapshot = self._snapshot(response)
            except (OSError, ValueError, CommandError) as error:
                warnings.append(f"Herdr session {name}: {error}")
                continue

            # Discover each collection independently. Release/protocol labels
            # say nothing about whether these native targets are available.
            collections = {
                key: self._rows(snapshot, key, id_key, name, warnings)
                for key, id_key in (
                    ("workspaces", "workspace_id"),
                    ("tabs", "tab_id"),
                    ("panes", "pane_id"),
                    ("agents", "pane_id"),
                )
            }

            identity = (socket_path, server_pid, birth, socket_info.st_dev, socket_info.st_ino)
            hosts = self._session_hosts(context, name)
            session_id = stable_id(self.name, *identity, "session", name)
            focused_workspace = str(snapshot.get("focused_workspace_id") or "")
            focused_tab = str(snapshot.get("focused_tab_id") or "")
            focused_pane = str(snapshot.get("focused_pane_id") or "")
            items.append(
                Thing(
                    id=session_id,
                    kind="herdr-session",
                    provider="Herdr",
                    title=name,
                    context=f"Herdr {snapshot.get('version') or ''} · local session".strip(" ·"),
                    search_terms=["herdr", socket_path],
                    badges=["Session", "Attached" if hosts else "Detached"],
                    active=bool(hosts and focused_workspace),
                    recency=3000 if hosts else 0,
                    activation=self._activation(socket_path, name, server_pid, birth, "session", "", hosts),
                )
            )

            workspace_ids: dict[str, str] = {}
            tab_ids: dict[str, str] = {}
            pane_ids: dict[str, str] = {}
            for workspace in collections["workspaces"]:
                native_id = workspace["workspace_id"]
                item_id = stable_id(self.name, *identity, "workspace", native_id)
                workspace_ids[native_id] = item_id
                status = str(workspace.get("agent_status") or "unknown")
                title = str(workspace.get("label") or native_id)
                items.append(
                    Thing(
                        id=item_id,
                        kind="herdr-workspace",
                        provider="Herdr",
                        title=title,
                        context=f"{workspace.get('tab_count', 0)} tabs · {workspace.get('pane_count', 0)} panes",
                        search_terms=["herdr", name, native_id, status],
                        parent_id=session_id,
                        badges=["Workspace", status.title()],
                        active=native_id == focused_workspace,
                        recency=3400 if native_id == focused_workspace else 0,
                        activation=self._activation(
                            socket_path, name, server_pid, birth, "workspace", native_id, hosts
                        ),
                    )
                )
            for tab in collections["tabs"]:
                native_id = tab["tab_id"]
                workspace_id = str(tab.get("workspace_id") or "")
                item_id = stable_id(self.name, *identity, "tab", native_id)
                tab_ids[native_id] = item_id
                status = str(tab.get("agent_status") or "unknown")
                items.append(
                    Thing(
                        id=item_id,
                        kind="herdr-tab",
                        provider="Herdr",
                        title=str(tab.get("label") or f"Tab {tab.get('number') or native_id}"),
                        context=f"{tab.get('pane_count', 0)} panes · {name}",
                        search_terms=["herdr", workspace_id, native_id, status],
                        parent_id=workspace_ids.get(workspace_id, session_id),
                        badges=["Tab", status.title()],
                        active=native_id == focused_tab,
                        recency=3600 if native_id == focused_tab else 0,
                        activation=self._activation(socket_path, name, server_pid, birth, "tab", native_id, hosts),
                    )
                )
            for pane in collections["panes"]:
                native_id = pane["pane_id"]
                tab_id = str(pane.get("tab_id") or "")
                item_id = stable_id(self.name, *identity, "pane", native_id)
                pane_ids[native_id] = item_id
                cwd = canonical_path(str(pane.get("foreground_cwd") or pane.get("cwd") or ""))
                title = str(
                    pane.get("terminal_title_stripped")
                    or pane.get("terminal_title")
                    or Path(cwd).name
                    or native_id
                )
                status = str(pane.get("agent_status") or "unknown")
                items.append(
                    Thing(
                        id=item_id,
                        kind="herdr-pane",
                        provider="Herdr",
                        title=title,
                        context=cwd or name,
                        search_terms=["herdr", native_id, tab_id, status],
                        parent_id=tab_ids.get(tab_id, session_id),
                        badges=["Pane", status.title()],
                        active=native_id == focused_pane,
                        recency=3800 if native_id == focused_pane else 0,
                        activation=self._activation(socket_path, name, server_pid, birth, "pane", native_id, hosts),
                    )
                )
                panes_metadata.append(
                    {
                        "item_id": item_id,
                        "session": name,
                        "socket": socket_path,
                        "server_pid": server_pid,
                        "birth": birth,
                        "pane_id": native_id,
                        "cwd": cwd,
                        "title": title,
                        "activation": self._activation(
                            socket_path, name, server_pid, birth, "pane", native_id, hosts
                        ),
                    }
                )
            for agent in collections["agents"]:
                pane_id = agent["pane_id"]
                reference = agent.get("agent_session") if isinstance(agent.get("agent_session"), dict) else {}
                identity_value = str(reference.get("value") or pane_id)
                agent_name = str(agent.get("agent") or "Agent")
                status = str(agent.get("agent_status") or "unknown")
                item_id = stable_id(self.name, *identity, "agent", agent_name, identity_value, pane_id)
                cwd = canonical_path(str(agent.get("foreground_cwd") or agent.get("cwd") or ""))
                terminal_title = str(agent.get("terminal_title_stripped") or agent.get("terminal_title") or "")
                items.append(
                    Thing(
                        id=item_id,
                        kind="herdr-agent",
                        provider="Herdr",
                        title=terminal_title or agent_name.title(),
                        context=cwd or name,
                        search_terms=["herdr", agent_name, identity_value, pane_id, status],
                        parent_id=pane_ids.get(pane_id, session_id),
                        badges=[agent_name.title(), status.title()],
                        active=pane_id == focused_pane and bool(agent.get("focused")),
                        recency=4000 if pane_id == focused_pane else self._agent_recency(agent),
                        activation=self._activation(socket_path, name, server_pid, birth, "pane", pane_id, hosts),
                    )
                )
            sessions_metadata.append(
                {
                    "name": name,
                    "socket": socket_path,
                    "server_pid": server_pid,
                    "birth": birth,
                    "hosts": hosts,
                }
            )
        return ProviderResult(
            self.name,
            items,
            warnings,
            {"panes": panes_metadata, "sessions": sessions_metadata},
        )

    @staticmethod
    def _native_id(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip()) and not any(
            character in value for character in ("\x00", "\n", "\r")
        )

    @classmethod
    def _rows(
        cls, snapshot: dict[str, Any], key: str, id_key: str,
        session_name: str, warnings: list[str],
    ) -> list[dict[str, Any]]:
        rows = snapshot.get(key, [])
        if not isinstance(rows, list):
            warnings.append(f"Herdr session {session_name}: {key} collection is not an array")
            return []
        valid = [row for row in rows if isinstance(row, dict) and cls._native_id(row.get(id_key))]
        counts: dict[str, int] = {}
        for row in valid:
            native_id = row[id_key]
            counts[native_id] = counts.get(native_id, 0) + 1
        unique = [row for row in valid if counts[row[id_key]] == 1]
        if len(unique) != len(rows):
            warnings.append(f"Herdr session {session_name}: {key} contains invalid or ambiguous native IDs")
        return unique

    @staticmethod
    def _agent_recency(agent: dict[str, Any]) -> float:
        value = agent.get("state_change_seq")
        # Optional ranking metadata must not disable native discovery.
        return value % 1000 if isinstance(value, int) and not isinstance(value, bool) else 0

    @staticmethod
    def _snapshot(response: dict[str, Any]) -> dict[str, Any]:
        if isinstance(response.get("error"), dict):
            raise CommandError(str(response["error"].get("message") or "Herdr request failed"))
        result = response.get("result")
        if not isinstance(result, dict) or result.get("type") != "session_snapshot":
            raise CommandError("Herdr did not return a session snapshot")
        snapshot = result.get("snapshot")
        if not isinstance(snapshot, dict):
            raise CommandError("Herdr snapshot payload is missing")
        return snapshot

    @staticmethod
    def _validate_socket(path: str) -> os.stat_result | None:
        if not os.path.isabs(path):
            return None
        try:
            info = os.stat(path, follow_symlinks=False)
        except OSError:
            return None
        return info if info.st_uid == os.getuid() and stat.S_ISSOCK(info.st_mode) else None

    @staticmethod
    def _server_pid_for_socket(socket_path: str, context: ScanContext) -> int:
        socket_inode = ""
        try:
            for line in Path("/proc/net/unix").read_text(encoding="utf-8").splitlines()[1:]:
                fields = line.split(maxsplit=7)
                if len(fields) >= 8 and fields[7] == socket_path:
                    socket_inode = fields[6]
                    break
        except OSError:
            return 0
        if not socket_inode:
            return 0
        marker = f"socket:[{socket_inode}]"
        for process in context.processes.named("herdr"):
            if "server" not in process.argv:
                continue
            fd_dir = Path("/proc", str(process.pid), "fd")
            try:
                if any(os.readlink(entry) == marker for entry in fd_dir.iterdir()):
                    return process.pid
            except OSError:
                continue
        return 0

    @staticmethod
    def _session_hosts(context: ScanContext, session_name: str) -> list[dict[str, str]]:
        managed_pids = {int(client.get("pid") or 0) for client in context.hypr_clients}
        hosts: list[dict[str, str]] = []
        for process in HerdrProvider._session_processes(context, session_name):
            ancestor = context.processes.ancestor_pid_in(process.pid, managed_pids)
            clients = context.clients_for_pid(ancestor or 0)
            # A shared terminal PID does not identify one Foot server window.
            if len(clients) != 1:
                continue
            client = clients[0]
            host = {"address": normalized_address(client.get("address")), "pid": str(ancestor)}
            if host not in hosts:
                hosts.append(host)
        return hosts

    @staticmethod
    def _session_processes(context: ScanContext, session_name: str) -> list[Any]:
        return [
            process
            for process in context.processes.named("herdr")
            if HerdrProvider._client_session(process.argv) == session_name
        ]

    @staticmethod
    def _client_session(argv: tuple[str, ...] | list[str]) -> str | None:
        """Return the local session an argv attaches to as an app client.

        The server, one-shot API commands such as `herdr pane list` (which
        agents run from inside panes), and `--remote`/`--machine` invocations
        are not clients of a local session and yield None.
        """

        session = "default"
        positionals: list[str] = []
        arguments = list(argv[1:])
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "--session":
                if index + 1 >= len(arguments):
                    return None
                session = arguments[index + 1]
                index += 2
                continue
            if argument.startswith("--session="):
                session = argument.split("=", 1)[1]
            elif argument.startswith("-"):
                return None
            else:
                positionals.append(argument)
            index += 1
        if positionals in ([], ["client"]):
            return session
        if len(positionals) == 3 and positionals[:2] == ["session", "attach"]:
            return positionals[2]
        return None

    @staticmethod
    def _activation(
        socket_path: str,
        session_name: str,
        server_pid: int,
        birth: str,
        target_kind: str,
        target_id: str,
        hosts: list[dict[str, str]],
    ) -> dict[str, Any]:
        try:
            socket_info = os.stat(socket_path, follow_symlinks=False)
            socket_dev = socket_info.st_dev
            socket_ino = socket_info.st_ino
        except OSError:
            socket_dev = 0
            socket_ino = 0
        return {
            "socket": socket_path,
            "session": session_name,
            "server_pid": server_pid,
            "birth": birth,
            "socket_dev": socket_dev,
            "socket_ino": socket_ino,
            "target_kind": target_kind,
            "target_id": target_id,
            "hosts": hosts,
        }

    async def activate(self, activation: dict[str, Any], context: ScanContext) -> None:
        socket_path = str(activation.get("socket") or "")
        socket_info = self._validate_socket(socket_path)
        if not socket_info:
            raise CommandError("Herdr session socket closed")
        if (
            int(activation.get("socket_dev") or 0) != socket_info.st_dev
            or int(activation.get("socket_ino") or 0) != socket_info.st_ino
        ):
            raise CommandError("Herdr session socket was replaced")
        server_pid = int(activation.get("server_pid") or 0)
        if server_pid and process_birth(server_pid) != str(activation.get("birth")):
            raise CommandError("Herdr server was replaced")
        kind = str(activation.get("target_kind") or "")
        target_id = activation.get("target_id")
        if kind not in {"session", "workspace", "tab", "pane"}:
            raise CommandError("Unknown Herdr activation target")
        if kind != "session" and not self._native_id(target_id):
            raise CommandError("Herdr target has no exact native ID")
        method = {"workspace": "workspace.focus", "tab": "tab.focus", "pane": "pane.focus"}.get(kind)
        if method:
            key = kind + "_id"
            response = await unix_json_request(
                socket_path,
                {"id": "everything:focus", "method": method, "params": {key: target_id}},
                timeout=1.0,
            )
            if isinstance(response.get("error"), dict):
                raise CommandError(str(response["error"].get("message") or "Herdr target closed"))
            if not isinstance(response.get("result"), dict):
                raise CommandError("Herdr focus did not return a result")

        routes = [
            route
            for process in self._session_processes(
                context, str(activation.get("session") or "default")
            )
            if (route := route_for_process(context, process.pid, cwd=process.cwd)) is not None
        ]
        if len(routes) == 1:
            route = routes[0]
            provider_name = str(route.get("provider") or "")
            provider = context.providers.get(provider_name)
            if provider:
                await provider.activate(dict(route.get("activation") or {}), context)
            elif provider_name == "hyprland":
                await focus_address(
                    context, str(route.get("activation", {}).get("address") or "")
                )
            else:
                raise CommandError("Herdr terminal route is unavailable")
            return

        if activation.get("allow_new_client") is False:
            return

        await launch_terminal_and_focus(
            context,
            ["omarchy-launch-terminal", "herdr", "session", "attach", str(activation.get("session") or "default")]
        )
