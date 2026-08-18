from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from ..commands import CommandError
from ..model import Thing, process_birth, stable_id
from ..processes import canonical_path, username
from .base import ProviderResult, ScanContext, normalized_address
from .hyprland import launch_terminal_and_focus


QUERY_EXPR = (
    "luaeval('vim.json.encode({pid=vim.fn.getpid(),current=vim.api.nvim_get_current_buf(),"
    "cwd=vim.fn.getcwd(),"
    "terminal_title=(vim.o.title and vim.o.titlestring or \"\"),buffers="
    "vim.tbl_map(function(b) return {bufnr=b.bufnr,name=b.name,changed=b.changed,"
    "loaded=b.loaded,listed=b.listed,windows=vim.fn.win_findbuf(b.bufnr),"
    "lastused=b.lastused,changedtick=vim.api.nvim_buf_get_changedtick(b.bufnr)} end,"
    "vim.fn.getbufinfo({buflisted=1}))})')"
)


class NeovimProvider:
    name = "neovim"

    @staticmethod
    def _runtime_sockets(root: str, *, max_entries: int = 4096) -> set[str]:
        """Find current Nvim sockets directly below a run dir or its tempdir.

        Current Nvim may use either `<run>/nvim.PID.N` or
        `<run>/<private-tempdir>/nvim.PID.N`. Traversal is deliberately one
        directory deep, same-user only, non-symlink, and entry bounded.
        """

        found: set[str] = set()
        try:
            root_info = os.stat(root, follow_symlinks=False)
        except OSError:
            return found
        if root_info.st_uid != os.getuid() or not stat.S_ISDIR(root_info.st_mode):
            return found
        pending: list[tuple[str, int]] = [(root, 0)]
        inspected = 0
        while pending and inspected < max_entries:
            directory, depth = pending.pop()
            try:
                entries = os.scandir(directory)
            except OSError:
                continue
            with entries:
                for entry in entries:
                    inspected += 1
                    if inspected > max_entries:
                        break
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if info.st_uid != os.getuid():
                        continue
                    if stat.S_ISSOCK(info.st_mode) and entry.name.startswith("nvim"):
                        found.add(entry.path)
                    elif depth == 0 and stat.S_ISDIR(info.st_mode):
                        pending.append((entry.path, 1))
        return found

    def discover_sockets(self, context: ScanContext) -> list[str]:
        candidates: set[str] = set()
        runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        temp_root = os.environ.get("TMPDIR") or "/tmp"
        for pattern_root in (runtime, os.path.join(temp_root, "nvim." + username())):
            candidates.update(self._runtime_sockets(pattern_root))
        for process in context.processes.named("nvim", "neovim"):
            argv = list(process.argv)
            for index, argument in enumerate(argv[:-1]):
                if argument == "--listen":
                    candidates.add(os.path.abspath(os.path.expanduser(argv[index + 1])))

        out: list[str] = []
        for candidate in sorted(candidates):
            try:
                info = os.stat(candidate, follow_symlinks=False)
            except OSError:
                continue
            if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
                continue
            out.append(os.path.realpath(candidate))
        return sorted(set(out))

    async def _query(self, context: ScanContext, socket: str) -> dict[str, Any]:
        result = await context.runner.run(
            ["nvim", "--server", socket, "--remote-expr", QUERY_EXPR], timeout=1.2
        )
        if result.returncode != 0:
            raise CommandError(result.stderr.strip() or "Neovim socket did not answer")
        try:
            value = json.loads(result.stdout.strip())
            if isinstance(value, str):
                value = json.loads(value)
        except json.JSONDecodeError as error:
            raise CommandError("Neovim returned invalid buffer JSON") from error
        if not isinstance(value, dict) or not isinstance(value.get("buffers"), list):
            raise CommandError("Neovim buffer response has the wrong shape")
        return value

    async def scan(self, context: ScanContext) -> ProviderResult:
        items: list[Thing] = []
        warnings: list[str] = []
        servers: list[dict[str, Any]] = []
        for socket in self.discover_sockets(context):
            try:
                response = await self._query(context, socket)
            except CommandError as error:
                warnings.append(f"Neovim socket {Path(socket).name}: {error}")
                continue
            pid = int(response.get("pid") or 0)
            process = context.processes.get(pid)
            executable = (
                os.path.basename(process.argv[0]).lower()
                if process and process.argv
                else ""
            )
            if not process or (
                process.comm.lower() not in {"nvim", "neovim"}
                and executable not in {"nvim", "neovim"}
            ):
                warnings.append(
                    f"Neovim socket {Path(socket).name} did not identify a current-user Nvim process"
                )
                continue
            birth = process.start_time
            current = int(response.get("current") or 0)
            editor_cwd = canonical_path(str(response.get("cwd") or (process.cwd if process else "")))
            terminal_title = str(response.get("terminal_title") or "")
            route, parent_id, ambiguous_ghostty = self._route(
                context, pid, editor_cwd, terminal_title
            )
            last_used_values = [
                float(buffer.get("lastused") or 0)
                for buffer in response["buffers"]
                if isinstance(buffer, dict)
            ]
            newest_last_used = max(last_used_values, default=0.0)
            for buffer in response["buffers"]:
                if not isinstance(buffer, dict) or not buffer.get("listed", True):
                    continue
                bufnr = int(buffer.get("bufnr") or 0)
                if bufnr <= 0:
                    continue
                name = canonical_path(str(buffer.get("name") or ""))
                title = Path(name).name if name else f"[No Name {bufnr}]"
                changed = bool(buffer.get("changed"))
                loaded = bool(buffer.get("loaded"))
                windows = [int(value) for value in buffer.get("windows", []) if str(value).isdigit()]
                item_id = stable_id(self.name, socket, pid, birth, bufnr, name or "unnamed")
                badges = ["Buffer"]
                if changed:
                    badges.append("Modified")
                if not loaded:
                    badges.append("Unloaded")
                if windows:
                    badges.append("Visible")
                last_used = float(buffer.get("lastused") or 0)
                recent = max(0.0, 1000.0 - min(1000.0, newest_last_used - last_used))
                activation = {
                    "socket": socket,
                    "pid": pid,
                    "birth": birth,
                    "bufnr": bufnr,
                    "name": name,
                    "route": route,
                    "ambiguous_ghostty": ambiguous_ghostty,
                }
                items.append(
                    Thing(
                        id=item_id,
                        kind="neovim-buffer",
                        provider="Neovim",
                        title=title + (" [+]" if changed else ""),
                        context=name or f"Neovim server {Path(socket).name}",
                        search_terms=["neovim", "nvim", name, str(bufnr)],
                        parent_id=parent_id,
                        badges=badges,
                        active=bufnr == current,
                        recency=(3900 if bufnr == current else 0) + recent,
                        activation=activation,
                    )
                )
            servers.append({"socket": socket, "pid": pid, "birth": birth, "route": route})
        return ProviderResult(self.name, items, warnings, {"servers": servers})

    @staticmethod
    def _route(
        context: ScanContext, pid: int, process_cwd: str, terminal_title: str = ""
    ) -> tuple[dict[str, Any], str, bool]:
        tmux_matches = []
        for pane in context.provider_metadata.get("tmux", {}).get("panes", []):
            pane_pid = int(pane.get("pane_pid") or 0)
            if pane_pid and context.processes.is_descendant(pid, pane_pid):
                tmux_matches.append(pane)
        if len(tmux_matches) == 1:
            pane = tmux_matches[0]
            return (
                {"provider": "tmux", "activation": pane.get("activation", {})},
                str(pane.get("item_id") or ""),
                False,
            )
        if len(tmux_matches) > 1:
            return ({"provider": "remote-ui"}, "", False)

        cwd = canonical_path(process_cwd)
        herdr_sessions = [
            session
            for session in context.provider_metadata.get("herdr", {}).get("sessions", [])
            if int(session.get("server_pid") or 0)
            and context.processes.is_descendant(pid, int(session.get("server_pid") or 0))
        ]
        herdr_server_pids = {int(session.get("server_pid") or 0) for session in herdr_sessions}
        herdr_environment = context.processes.environment(
            pid, ("HERDR_SOCKET_PATH", "HERDR_PANE_ID")
        )
        environment_matches = [
            pane
            for pane in context.provider_metadata.get("herdr", {}).get("panes", [])
            if str(pane.get("socket") or "")
            == str(herdr_environment.get("HERDR_SOCKET_PATH") or "")
            and str(pane.get("pane_id") or "")
            == str(herdr_environment.get("HERDR_PANE_ID") or "")
            and int(pane.get("server_pid") or 0) in herdr_server_pids
        ]
        if len(environment_matches) == 1:
            pane = environment_matches[0]
            return (
                {"provider": "herdr", "activation": pane.get("activation", {})},
                str(pane.get("item_id") or ""),
                False,
            )
        herdr_matches = [
            pane
            for pane in context.provider_metadata.get("herdr", {}).get("panes", [])
            if int(pane.get("server_pid") or 0) in herdr_server_pids
            and cwd
            and canonical_path(str(pane.get("cwd") or "")) == cwd
        ]
        if len(herdr_matches) == 1:
            pane = herdr_matches[0]
            return (
                {"provider": "herdr", "activation": pane.get("activation", {})},
                str(pane.get("item_id") or ""),
                False,
            )
        if herdr_sessions:
            # The protocol does not expose pane process IDs. Never route a
            # nested editor to a same-cwd lookalike; a fresh remote UI is the
            # safe fallback when its owning Herdr pane is not unique.
            return ({"provider": "remote-ui"}, "", False)

        for provider_name in ("kitty", "ghostty"):
            process_surfaces = [
                surface
                for surface in context.provider_metadata.get(provider_name, {}).get("surfaces", [])
                if int(surface.get("pid") or 0)
                and context.processes.is_descendant(pid, int(surface.get("pid") or 0))
            ]
            if not process_surfaces:
                continue
            if len(process_surfaces) == 1:
                surface_matches = process_surfaces
            else:
                surface_matches = [
                    surface
                    for surface in process_surfaces
                    if cwd
                    and canonical_path(str(surface.get("cwd") or "")) == cwd
                    and terminal_title
                    and str(surface.get("title") or "") == terminal_title
                ]
            if len(surface_matches) == 1:
                surface = surface_matches[0]
                return (
                    {"provider": provider_name, "activation": surface.get("activation", {})},
                    str(surface.get("item_id") or ""),
                    False,
                )
            # A terminal process with multiple internal surfaces must match
            # exact title plus canonical cwd. Otherwise opening a new client
            # is safer than focusing a plausible but unproven sibling.
            return ({"provider": "remote-ui"}, "", provider_name == "ghostty")

        managed_pids = {int(client.get("pid") or 0) for client in context.hypr_clients}
        ancestor = context.processes.ancestor_pid_in(pid, managed_pids)
        clients = context.clients_for_pid(ancestor or 0)
        if len(clients) == 1:
            client = clients[0]
            address = normalized_address(client.get("address"))
            parent_id = ""
            for metadata in context.provider_metadata.get("hyprland", {}).get("clients", []):
                if normalized_address(metadata.get("address")) == address:
                    parent_id = str(metadata.get("item_id") or "")
                    break
            return (
                {
                    "provider": "hyprland",
                    "activation": {
                        "address": address,
                        "pid": int(client.get("pid") or 0),
                        "birth": process_birth(int(client.get("pid") or 0)),
                    },
                },
                parent_id,
                False,
            )
        return ({"provider": "remote-ui"}, "", False)

    async def activate(self, activation: dict[str, Any], context: ScanContext) -> None:
        socket = str(activation.get("socket") or "")
        pid = int(activation.get("pid") or 0)
        if process_birth(pid) != str(activation.get("birth")):
            raise CommandError("Neovim server was replaced")
        try:
            info = os.stat(socket, follow_symlinks=False)
        except OSError as error:
            raise CommandError("Neovim socket closed") from error
        if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
            raise CommandError("Neovim socket is not a current-user socket")

        bufnr = int(activation.get("bufnr") or 0)
        current = await self._query(context, socket)
        if int(current.get("pid") or 0) != pid:
            raise CommandError("Neovim socket was replaced")
        buffer = next(
            (value for value in current["buffers"] if isinstance(value, dict) and int(value.get("bufnr") or 0) == bufnr),
            None,
        )
        if not buffer or canonical_path(str(buffer.get("name") or "")) != str(activation.get("name") or ""):
            raise CommandError("Neovim buffer closed or its number was reused")

        # win_findbuf reaches an already displayed buffer (including another
        # tab page). Otherwise :hide permits changing the current buffer
        # without discarding a modified buffer. The fixed numeric result makes
        # this same RPC authoritative when deciding whether a new client is
        # permitted; a layout mutation between validation and selection cannot
        # cause an unnecessary terminal launch.
        expression = (
            "luaeval('(function(b) local w=vim.fn.win_findbuf(b); "
            "if #w>0 then vim.api.nvim_set_current_win(w[1]); return 1 else "
            "vim.cmd(\"hide buffer \"..b); return 0 end end)(_A)',"
            + str(bufnr)
            + ")"
        )
        result = await context.runner.run(
            ["nvim", "--server", socket, "--remote-expr", expression], timeout=1.2
        )
        if result.returncode != 0:
            raise CommandError(result.stderr.strip() or "Neovim refused the buffer switch")
        selection_result = result.stdout.strip()
        if selection_result not in {"0", "1"}:
            raise CommandError("Neovim returned an invalid buffer switch result")
        used_existing_window = selection_result == "1"

        route = activation.get("route") if isinstance(activation.get("route"), dict) else {}
        route_provider = str(route.get("provider") or "remote-ui")
        if route_provider in context.providers:
            route_activation = dict(route.get("activation") or {})
            if used_existing_window:
                route_activation["allow_new_client"] = False
            await context.providers[route_provider].activate(route_activation, context)

        if route_provider == "remote-ui" and not used_existing_window:
            await launch_terminal_and_focus(
                context,
                ["omarchy-launch-terminal", "nvim", "--server", socket, "--remote-ui"]
            )
