from __future__ import annotations

import json
import os
import socket
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from everything.commands import CommandError, CommandResult
from everything.processes import ProcTable, ProcessInfo
from everything.providers.base import ScanContext, route_for_process
from everything.providers.ghostty import (
    Atspi,
    EffectiveBinding,
    GhosttyProvider,
    PaletteState,
    parse_keybindings,
)
from everything.providers.hyprland import HyprlandProvider
from everything.providers.hyprland import launch_terminal_and_focus
from everything.providers.herdr import HerdrProvider
from everything.providers.kitty import KittyProvider
from everything.providers.neovim import NeovimProvider


class FakeRunner:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.calls: list[tuple[str, ...]] = []

    async def run(self, argv, **_kwargs):
        command = tuple(str(value) for value in argv)
        self.calls.append(command)
        return CommandResult(command, 0, self.stdout, "")


class HyprlandTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_mapped_clients_become_items(self) -> None:
        clients = [
            {
                "address": "0xabc",
                "mapped": True,
                "hidden": True,
                "class": "foot",
                "title": "shell",
                "pid": 999999,
                "workspace": {"id": -99, "name": "special:scratch"},
                "grouped": ["0xdef"],
                "focusHistoryID": 4,
            },
            {"address": "0xdef", "mapped": False, "class": "ignored", "pid": 1},
        ]
        context = ScanContext(FakeRunner(json.dumps(clients)), ProcTable({}))  # type: ignore[arg-type]
        result = await HyprlandProvider().scan(context)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].kind, "window")
        self.assertIn("Hidden", result.items[0].badges)
        self.assertIn("Scratchpad", result.items[0].badges)
        self.assertNotIn("process", result.items[0].kind)


class HerdrTests(unittest.TestCase):
    def test_protocol_snapshot_shape_is_strict(self) -> None:
        snapshot = {"protocol": 20, "workspaces": []}
        parsed = HerdrProvider._snapshot(
            {"id": "x", "result": {"type": "session_snapshot", "snapshot": snapshot}}
        )
        self.assertIs(parsed, snapshot)
        with self.assertRaises(Exception):
            HerdrProvider._snapshot({"id": "x", "result": {"type": "other"}})


class GhosttyBindingTests(unittest.TestCase):
    def test_effective_bindings_are_parsed_without_shell_text(self) -> None:
        parsed = parse_keybindings(
            "keybind = alt+1=goto_tab:1\n"
            "keybind = ctrl+tab=next_tab\n"
            "keybind = ctrl+shift+p=toggle_command_palette\n"
            "keybind = global:ctrl+p=toggle_command_palette\n"
            "keybind = ctrl+a>2=goto_tab:2\n"
        )
        self.assertEqual(parsed["goto_tab:1"], [EffectiveBinding("ALT", "1")])
        self.assertEqual(parsed["next_tab"], [EffectiveBinding("CTRL", "TAB")])
        self.assertEqual(
            parsed["toggle_command_palette"], [EffectiveBinding("CTRL + SHIFT", "P")]
        )
        self.assertNotIn("goto_tab:2", parsed)


class PaletteWalker(GhosttyProvider):
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        super().__init__()
        self.rows = rows
        self.index = 0

    async def _wait_selected(self, _palette):
        return self.rows[self.index] if self.index < len(self.rows) else None

    @staticmethod
    def _row_values(accessible):
        return accessible

    @staticmethod
    def _row_marker(accessible):
        return "|".join(accessible)

    async def _send_verified_key(self, _context, _address, _palette, key, mods=""):
        del mods
        if key == "DOWN":
            self.index += 1

    async def _wait_row_change(self, _palette, _marker):
        return self.index < len(self.rows)


class FakePaletteAccessible:
    def __init__(self, role_value, name: str, *children, editable: bool = False) -> None:
        self.role_value = role_value
        self.name = name
        self.children = list(children)
        self.editable = editable
        self.parent = None
        self.path = "fake:" + name
        for child in self.children:
            child.parent = self

    def get_role(self):
        return self.role_value

    def get_name(self):
        return self.name

    def get_description(self):
        return ""

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index]

    def get_parent(self):
        return self.parent

    def get_index_in_parent(self):
        return self.parent.children.index(self) if self.parent else 0

    def get_state_set(self):
        return type("State", (), {"contains": lambda _self, _value: False})()

    def get_editable_text_iface(self):
        return self if self.editable else None

    def get_text_iface(self):
        return None

    def get_accessible_id(self):
        return self.path


class GhosttyPaletteTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipIf(Atspi is None, "PyGObject AT-SPI is unavailable")
    async def test_palette_search_and_list_must_share_a_modal(self) -> None:
        row = FakePaletteAccessible(Atspi.Role.LIST_ITEM, "Focus: Surface")
        list_view = FakePaletteAccessible(Atspi.Role.LIST, "Commands", row)
        search = FakePaletteAccessible(
            Atspi.Role.ENTRY, "Execute a command", editable=True
        )
        dialog = FakePaletteAccessible(Atspi.Role.DIALOG, "Command Palette", search, list_view)
        application = FakePaletteAccessible(Atspi.Role.APPLICATION, "Ghostty", dialog)
        palette = GhosttyProvider._find_palette(application)
        self.assertIsNotNone(palette)
        self.assertIs(palette.search, search)  # type: ignore[union-attr]
        self.assertIs(palette.list_view, list_view)  # type: ignore[union-attr]

        frame = FakePaletteAccessible(Atspi.Role.FRAME, "Terminal", search, list_view)
        application = FakePaletteAccessible(Atspi.Role.APPLICATION, "Ghostty", frame)
        self.assertIsNone(GhosttyProvider._find_palette(application))

    async def test_virtualized_rows_and_duplicate_occurrences_are_complete(self) -> None:
        rows = [(f"Focus: Surface {index}", f"/work/{index}") for index in range(11)]
        rows.extend([("Focus: Duplicate", "/same"), ("Focus: Duplicate", "/same")])
        provider = PaletteWalker(rows)
        result = await provider._walk_rows(None, "0xabc", PaletteState(None, None, None))  # type: ignore[arg-type]
        self.assertEqual(len(result), 13)
        self.assertEqual(result[-2].occurrence, 1)
        self.assertEqual(result[-1].occurrence, 2)
        self.assertEqual(result[-1].ordinal, 12)

    async def test_palette_scan_fails_if_selection_leaves_focus_rows(self) -> None:
        provider = PaletteWalker([("Focus: One", "/one"), ("Close window", "")])
        with self.assertRaises(CommandError):
            await provider._walk_rows(None, "0xabc", PaletteState(None, None, None))  # type: ignore[arg-type]

    async def test_navigation_uses_exact_address_key_state_pairs(self) -> None:
        runner = FakeRunner("ok\n")
        context = ScanContext(runner, ProcTable({}))  # type: ignore[arg-type]
        palette = PaletteState(object(), object(), object())
        with patch.object(GhosttyProvider, "_find_palette", return_value=palette), patch(
            "everything.providers.ghostty._text_value", return_value="Focus:"
        ):
            await GhosttyProvider()._send_verified_key(context, "0xabc", palette, "DOWN")
        self.assertEqual(len(runner.calls), 2)
        expressions = [call[2] for call in runner.calls]
        self.assertTrue(all("hl.dsp.send_key_state" in value for value in expressions))
        self.assertTrue(all('window = "address:0xabc"' in value for value in expressions))
        self.assertTrue(all('key = "DOWN"' in value for value in expressions))
        self.assertIn('state = "down"', expressions[0])
        self.assertIn('state = "up"', expressions[1])
        self.assertTrue(all("sendshortcut" not in value for value in expressions))

    async def test_palette_action_has_capability_checked_binding_fallback(self) -> None:
        class CapabilityRunner:
            async def run(self, argv, **_kwargs):
                command = tuple(str(value) for value in argv)
                if command[1] == "+list-actions":
                    return CommandResult(command, 0, "toggle_command_palette\n", "")
                return CommandResult(
                    command, 0, "keybind = ctrl+shift+p=toggle_command_palette\n", ""
                )

        provider = GhosttyProvider()
        provider._send_binding = AsyncMock()  # type: ignore[method-assign]
        context = ScanContext(CapabilityRunner(), ProcTable({}))  # type: ignore[arg-type]
        top = type("Top", (), {"accessible": object(), "client": {"address": "0xabc"}})()
        with patch("everything.providers.ghostty.walk", return_value=[]):
            await provider._toggle_command_palette(context, top)  # type: ignore[arg-type]
        provider._send_binding.assert_awaited_once_with(  # type: ignore[attr-defined]
            context, "0xabc", EffectiveBinding("CTRL + SHIFT", "P")
        )


class KittyIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def _scan_with_inode(self, inode: int):
        payload = [
            {
                "id": 4,
                "tabs": [
                    {
                        "id": 5,
                        "title": "Project",
                        "windows": [
                            {"id": 6, "title": "Editor", "cwd": "/work", "is_focused": True}
                        ],
                    }
                ],
            }
        ]
        provider = KittyProvider()
        provider.sockets = lambda _context: [  # type: ignore[method-assign]
            ("/run/user/1000/omarchy-kitty-17", 17, "99", 7, inode)
        ]
        context = ScanContext(FakeRunner(json.dumps(payload)), ProcTable({}))  # type: ignore[arg-type]
        return await provider.scan(context)

    async def test_socket_device_and_inode_are_part_of_identity(self) -> None:
        first = await self._scan_with_inode(101)
        replacement = await self._scan_with_inode(102)
        self.assertEqual(len(first.items), 2)
        self.assertNotEqual(first.items[0].id, replacement.items[0].id)
        self.assertEqual(first.items[0].activation["socket_dev"], 7)
        self.assertEqual(first.items[0].activation["socket_ino"], 101)


class NeovimRoutingTests(unittest.TestCase):
    @staticmethod
    def context() -> ScanContext:
        processes = {
            10: ProcessInfo(10, 1, "a", "herdr", ("herdr", "server"), "/project"),
            20: ProcessInfo(20, 10, "b", "bash", ("bash",), "/project"),
            30: ProcessInfo(30, 20, "c", "nvim", ("nvim",), "/project"),
            100: ProcessInfo(100, 1, "d", "ghostty", ("ghostty",), "/project"),
            110: ProcessInfo(110, 100, "e", "bash", ("bash",), "/project"),
            120: ProcessInfo(120, 110, "f", "nvim", ("nvim",), "/project"),
        }
        return ScanContext(FakeRunner(""), ProcTable(processes))  # type: ignore[arg-type]

    def test_herdr_same_cwd_ambiguity_opens_remote_ui(self) -> None:
        context = self.context()
        context.provider_metadata["herdr"] = {
            "sessions": [{"server_pid": 10}],
            "panes": [
                {"server_pid": 10, "cwd": "/project", "item_id": "one", "activation": {}},
                {"server_pid": 10, "cwd": "/project", "item_id": "two", "activation": {}},
            ],
        }
        route, parent, ambiguous_ghostty = NeovimProvider._route(context, 30, "/project")
        self.assertEqual(route["provider"], "remote-ui")
        self.assertEqual(parent, "")
        self.assertFalse(ambiguous_ghostty)

    def test_unique_herdr_pane_is_routed_first(self) -> None:
        context = self.context()
        activation = {"pane_id": "one"}
        context.provider_metadata["herdr"] = {
            "sessions": [{"server_pid": 10}],
            "panes": [
                {
                    "server_pid": 10,
                    "cwd": "/project",
                    "item_id": "herdr-pane",
                    "activation": activation,
                }
            ],
        }
        route, parent, _ambiguous = NeovimProvider._route(context, 30, "/project")
        self.assertEqual(route, {"provider": "herdr", "activation": activation})
        self.assertEqual(parent, "herdr-pane")

    def test_ghostty_requires_process_title_and_cwd_when_multi_surface(self) -> None:
        context = self.context()
        context.provider_metadata["ghostty"] = {
            "surfaces": [
                {
                    "pid": 100,
                    "cwd": "/project",
                    "title": "Editor",
                    "item_id": "editor",
                    "activation": {"surface": 1},
                },
                {
                    "pid": 100,
                    "cwd": "/project",
                    "title": "Shell",
                    "item_id": "shell",
                    "activation": {"surface": 2},
                },
            ]
        }
        route, parent, ambiguous = NeovimProvider._route(context, 120, "/project", "Editor")
        self.assertEqual(route["provider"], "ghostty")
        self.assertEqual(parent, "editor")
        self.assertFalse(ambiguous)

        route, parent, ambiguous = NeovimProvider._route(context, 120, "/project", "")
        self.assertEqual(route["provider"], "remote-ui")
        self.assertEqual(parent, "")
        self.assertTrue(ambiguous)


class HostRoutingTests(unittest.TestCase):
    def test_shared_foot_pid_is_never_guessed(self) -> None:
        processes = {
            10: ProcessInfo(10, 1, "a", "foot", ("foot", "--server"), "/"),
            20: ProcessInfo(20, 10, "b", "bash", ("bash",), "/work"),
        }
        context = ScanContext(FakeRunner(""), ProcTable(processes))  # type: ignore[arg-type]
        context.hypr_clients = [
            {"address": "0xaaa", "pid": 10, "class": "foot"},
            {"address": "0xbbb", "pid": 10, "class": "foot"},
        ]
        self.assertIsNone(route_for_process(context, 20, cwd="/work"))

    def test_single_internal_surface_routes_before_outer_window(self) -> None:
        processes = {
            100: ProcessInfo(100, 1, "a", "ghostty", ("ghostty",), "/work"),
            110: ProcessInfo(110, 100, "b", "bash", ("bash",), "/work"),
        }
        context = ScanContext(FakeRunner(""), ProcTable(processes))  # type: ignore[arg-type]
        context.hypr_clients = [{"address": "0xaaa", "pid": 100, "class": "ghostty"}]
        context.provider_metadata["ghostty"] = {
            "surfaces": [
                {
                    "pid": 100,
                    "item_id": "surface",
                    "activation": {"target": "surface"},
                }
            ]
        }
        route = route_for_process(context, 110, cwd="/work")
        self.assertEqual(route["provider"], "ghostty")  # type: ignore[index]
        self.assertEqual(route["item_id"], "surface")  # type: ignore[index]


class NeovimSocketTests(unittest.TestCase):
    def test_runtime_socket_walk_is_same_shape_and_one_level_deep(self) -> None:
        with tempfile.TemporaryDirectory(prefix="everything-nvim-") as root:
            nested = os.path.join(root, "private")
            too_deep = os.path.join(nested, "deeper")
            os.makedirs(too_deep)
            direct_path = os.path.join(root, "nvim.10.0")
            nested_path = os.path.join(nested, "nvim.11.0")
            deep_path = os.path.join(too_deep, "nvim.12.0")
            sockets = [socket.socket(socket.AF_UNIX) for _index in range(3)]
            try:
                for handle, path in zip(sockets, (direct_path, nested_path, deep_path)):
                    handle.bind(path)
                found = NeovimProvider._runtime_sockets(root)
            finally:
                for handle in sockets:
                    handle.close()
            self.assertEqual(found, {direct_path, nested_path})


class FreshTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_exact_address_is_detected_and_focused(self) -> None:
        class LaunchRunner:
            def __init__(self) -> None:
                self.client_reads = 0
                self.spawned = None
                self.focus_expression = ""

            async def run(self, argv, **_kwargs):
                command = tuple(str(value) for value in argv)
                if command[:3] == ("hyprctl", "-j", "clients"):
                    self.client_reads += 1
                    clients = [{"address": "0x0dd", "pid": 1, "class": "foot", "mapped": True}]
                    if self.client_reads > 1:
                        clients.append(
                            {"address": "0xbee", "pid": 2, "class": "foot", "mapped": True}
                        )
                    return CommandResult(command, 0, json.dumps(clients), "")
                self.focus_expression = command[2]
                return CommandResult(command, 0, "ok\n", "")

            async def spawn_detached(self, argv, **_kwargs):
                self.spawned = tuple(str(value) for value in argv)
                return 99

        runner = LaunchRunner()
        context = ScanContext(runner, ProcTable({}))  # type: ignore[arg-type]
        address = await launch_terminal_and_focus(
            context, ["omarchy-launch-terminal", "tmux", "attach"]
        )
        self.assertEqual(address, "0xbee")
        self.assertEqual(runner.spawned, ("omarchy-launch-terminal", "tmux", "attach"))
        self.assertIn('address:0xbee', runner.focus_expression)


if __name__ == "__main__":
    unittest.main()
