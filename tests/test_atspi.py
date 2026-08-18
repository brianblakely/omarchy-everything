from __future__ import annotations

import unittest
from unittest.mock import patch

from everything.commands import CommandRunner
from everything.processes import ProcTable
from everything.providers.atspi import (
    Atspi,
    AtspiProvider,
    AtspiTree,
    BROWSER_CLASS,
    NativeTab,
    TopLevel,
    is_browser_app_mode,
    invoke_accessible,
)
from everything.providers.base import ScanContext


class FakeStateSet:
    def __init__(self, selected: bool = False) -> None:
        self.selected = selected

    def contains(self, value) -> bool:
        return bool(Atspi and value == Atspi.StateType.SELECTED and self.selected)


class FakeAction:
    def __init__(self, names: tuple[str, ...] = ("activate",)) -> None:
        self.names = names
        self.invoked: list[int] = []

    def get_n_actions(self) -> int:
        return len(self.names)

    def get_action_name(self, index: int) -> str:
        return self.names[index]

    def do_action(self, index: int) -> bool:
        self.invoked.append(index)
        return True


class FakeAccessible:
    def __init__(
        self,
        role_value,
        name: str,
        *children,
        selected: bool = False,
        actionable: bool = False,
        accessible_id: str = "",
    ) -> None:
        self.role_value = role_value
        self.name = name
        self.children = list(children)
        self.state = FakeStateSet(selected)
        self.action = FakeAction() if actionable else None
        self.accessible_id = accessible_id

    def get_role(self):
        return self.role_value

    def get_name(self) -> str:
        return self.name

    def get_description(self) -> str:
        return ""

    def get_child_count(self) -> int:
        return len(self.children)

    def get_child_at_index(self, index: int):
        return self.children[index]

    def get_state_set(self):
        return self.state

    def get_action_iface(self):
        return self.action

    def get_component_iface(self):
        return object() if self.action else None

    def get_accessible_id(self) -> str:
        return self.accessible_id


@unittest.skipIf(Atspi is None, "PyGObject AT-SPI is unavailable")
class NativeTabTests(unittest.TestCase):
    @staticmethod
    def tab(name: str, identifier: str, selected: bool = False) -> FakeAccessible:
        return FakeAccessible(
            Atspi.Role.PAGE_TAB,
            name,
            selected=selected,
            actionable=True,
            accessible_id=identifier,
        )

    def test_document_and_tool_tabs_are_rejected(self) -> None:
        authored = FakeAccessible(
            Atspi.Role.PAGE_TAB_LIST,
            "Web page tabs",
            self.tab("ARIA one", "aria-1"),
            self.tab("ARIA two", "aria-2"),
        )
        document = FakeAccessible(Atspi.Role.DOCUMENT_WEB, "Page", authored)
        tools = FakeAccessible(
            Atspi.Role.PAGE_TAB_LIST,
            "Developer Tools",
            self.tab("Elements", "tool-1"),
        )
        native = FakeAccessible(
            Atspi.Role.PAGE_TAB_LIST,
            "Tab strip",
            self.tab("First", "native-1", selected=True),
            self.tab("Second", "native-2"),
        )
        root = FakeAccessible(Atspi.Role.FRAME, "Browser", document, tools, native)
        top = TopLevel(None, root, 10, 0, "Browser", {"address": "0xabc"})
        tree = AtspiTree.__new__(AtspiTree)

        tabs = tree.native_tabs(top, browser=True)

        self.assertEqual([tab.title for tab in tabs], ["First", "Second"])
        self.assertTrue(tabs[0].selected)

    def test_current_browser_families_are_recognized(self) -> None:
        classes = (
            "chromium",
            "google-chrome",
            "Brave-browser-beta",
            "microsoft-edge",
            "firefox",
            "zen-alpha",
            "vivaldi-stable",
            "helium",
            "librewolf",
        )
        self.assertTrue(all(BROWSER_CLASS.search(value) for value in classes))
        self.assertFalse(any(BROWSER_CLASS.search(value) for value in ("Citizen", "ledger", "frozen-app")))

    def test_browser_app_mode_is_distinct_from_normal_and_private_windows(self) -> None:
        app_mode_clients = (
            {
                "class": "chrome-github.com__-Default",
                "initialClass": "chrome-github.com__-Default",
                "initialTitle": "github.com_/",
            },
            {
                "class": "chromium-app.example.test__dashboard-Default",
                "initialTitle": "app.example.test_/dashboard",
            },
            {
                "class": "com.google.Chrome",
                "initialTitle": "mail.example.test_/inbox",
            },
        )
        normal_clients = (
            {"class": "chromium", "initialTitle": "New tab - Chromium"},
            {"class": "google-chrome", "initialTitle": "New Incognito Tab - Google Chrome"},
            {"class": "firefox", "initialTitle": "Mozilla Firefox Private Browsing"},
        )

        self.assertTrue(all(is_browser_app_mode(client) for client in app_mode_clients))
        self.assertFalse(any(is_browser_app_mode(client) for client in normal_clients))

    def test_chromium_default_action_activates_a_tab(self) -> None:
        tab = FakeAccessible(
            Atspi.Role.PAGE_TAB,
            "Native tab",
            actionable=True,
        )
        tab.action = FakeAction(("dodefault", "showcontextmenu"))

        self.assertTrue(invoke_accessible(tab))
        self.assertEqual(tab.action.invoked, [0])

    def test_provider_retries_first_seen_browser_until_tabs_are_available(self) -> None:
        client = {
            "address": "0xabc",
            "pid": 42,
            "class": "chromium",
            "title": "Current page - Chromium",
            "focusHistoryID": 0,
        }
        top = TopLevel(None, object(), 42, 0, client["title"], client)
        tab = NativeTab(
            accessible=object(),
            top=top,
            strip_path=(0,),
            tab_path=(0, 0),
            index=0,
            title="Current page",
            selected=True,
            native_id="native-tab-1",
        )

        class DelayedTree:
            scans = 0

            def top_levels(self, _context):
                return [top]

            def native_tabs(self, _top, *, browser):
                self.__class__.scans += 1
                return [tab] if browser and self.__class__.scans >= 2 else []

        context = ScanContext(
            runner=CommandRunner(),
            processes=ProcTable({}),
            hypr_clients=[client],
            provider_metadata={
                "hyprland": {
                    "clients": [{"address": "0xabc", "item_id": "hyprland:window"}]
                }
            },
        )
        provider = AtspiProvider()

        with patch("everything.providers.atspi.AtspiTree", DelayedTree), patch(
            "everything.providers.atspi.BROWSER_SETTLE_DELAYS", (0,)
        ), patch("everything.providers.atspi.process_birth", return_value="birth"):
            result = provider._scan_sync(context)

        self.assertEqual(DelayedTree.scans, 2)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].kind, "browser-tab")
        self.assertEqual(result.items[0].title, "Current page")
        self.assertEqual(result.items[0].parent_id, "hyprland:window")
        self.assertEqual(result.items[0].activation["address"], "0xabc")

    def test_provider_omits_app_mode_tabs_without_reclassifying_them(self) -> None:
        normal_client = {
            "address": "0xnormal",
            "pid": 42,
            "class": "chromium",
            "initialClass": "chromium",
            "title": "Current page - Chromium",
            "initialTitle": "New tab - Chromium",
            "focusHistoryID": 0,
        }
        app_client = {
            "address": "0xapp",
            "pid": 42,
            "class": "chrome-app.example.test__-Default",
            "initialClass": "chrome-app.example.test__-Default",
            "title": "Example app",
            "initialTitle": "app.example.test_/",
            "focusHistoryID": 1,
        }
        normal_top = TopLevel(None, object(), 42, 0, normal_client["title"], normal_client)
        app_top = TopLevel(None, object(), 42, 1, app_client["title"], app_client)

        class MixedTree:
            def top_levels(self, _context):
                return [normal_top, app_top]

            def native_tabs(self, top, *, browser):
                return [
                    NativeTab(
                        accessible=object(),
                        top=top,
                        strip_path=(0,),
                        tab_path=(0, 0),
                        index=0,
                        title="Normal tab" if top is normal_top else "App-mode tab",
                        selected=True,
                        native_id="normal-tab" if top is normal_top else "app-tab",
                    )
                ]

        context = ScanContext(
            runner=CommandRunner(),
            processes=ProcTable({}),
            hypr_clients=[normal_client, app_client],
            provider_metadata={
                "hyprland": {
                    "clients": [
                        {"address": "0xnormal", "item_id": "hyprland:normal"},
                        {"address": "0xapp", "item_id": "hyprland:app"},
                    ]
                }
            },
        )
        provider = AtspiProvider()

        with patch("everything.providers.atspi.AtspiTree", MixedTree), patch(
            "everything.providers.atspi.process_birth", return_value="birth"
        ):
            result = provider._scan_sync(context)

        self.assertEqual([item.title for item in result.items], ["Normal tab"])
        self.assertEqual(result.items[0].kind, "browser-tab")
        self.assertEqual(result.items[0].parent_id, "hyprland:normal")
        self.assertEqual(set(provider._browser_clients(context).values()), {"0xnormal"})


if __name__ == "__main__":
    unittest.main()
