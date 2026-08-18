from __future__ import annotations

import unittest

from everything.providers.atspi import Atspi, AtspiTree, BROWSER_CLASS, TopLevel


class FakeStateSet:
    def __init__(self, selected: bool = False) -> None:
        self.selected = selected

    def contains(self, value) -> bool:
        return bool(Atspi and value == Atspi.StateType.SELECTED and self.selected)


class FakeAction:
    def __init__(self, names: tuple[str, ...] = ("activate",)) -> None:
        self.names = names

    def get_n_actions(self) -> int:
        return len(self.names)

    def get_action_name(self, index: int) -> str:
        return self.names[index]


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


if __name__ == "__main__":
    unittest.main()
