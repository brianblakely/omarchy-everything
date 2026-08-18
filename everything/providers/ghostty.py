from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from ..commands import CommandError
from ..model import Thing, process_birth, stable_id
from ..processes import canonical_path
from .atspi import (
    Atspi,
    AtspiTree,
    GHOSTTY_CLASS,
    NativeTab,
    TopLevel,
    action_names,
    clean_text,
    folded,
    has_state,
    invoke_accessible,
    role,
    safe_call,
    walk,
)
from .base import ProviderResult, ScanContext, normalized_address
from .hyprland import focus_address, lua_string


FOCUS_PREFIX = "Focus:"
GHOSTTY_131 = re.compile(r"(?<![0-9.])1\.3\.1(?![0-9.])")


@dataclass(slots=True, frozen=True)
class PaletteFingerprint:
    title: str
    cwd: str
    occurrence: int
    ordinal: int

    def json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "cwd": self.cwd,
            "occurrence": self.occurrence,
            "ordinal": self.ordinal,
        }


@dataclass(slots=True)
class PaletteState:
    application: Any
    search: Any
    list_view: Any
    container: Any = None
    identity: str = ""


@dataclass(slots=True, frozen=True)
class EffectiveBinding:
    mods: str
    key: str


def parse_keybindings(output: str) -> dict[str, list[EffectiveBinding]]:
    parsed: dict[str, list[EffectiveBinding]] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("keybind") or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        if "=" not in value:
            continue
        trigger, action = value.rsplit("=", 1)
        trigger = trigger.strip()
        action = action.strip()
        if not trigger or not action or ">" in trigger or action.startswith("unbind"):
            continue
        # Scope/behavior prefixes are not key modifiers. Global/all bindings
        # are deliberately rejected because Everything targets one exact
        # managed window.
        prefixes = trigger.split(":")
        if len(prefixes) > 1:
            flags = {part.lower() for part in prefixes[:-1]}
            if flags.intersection({"global", "all", "unconsumed"}):
                continue
            trigger = prefixes[-1]
        components = [component.strip().lower() for component in trigger.split("+") if component.strip()]
        if not components:
            continue
        key = components[-1]
        modifiers = components[:-1]
        allowed = {"ctrl": "CTRL", "control": "CTRL", "shift": "SHIFT", "alt": "ALT", "super": "SUPER"}
        if any(modifier not in allowed for modifier in modifiers):
            continue
        key_names = {
            "page_down": "PAGEDOWN",
            "page_up": "PAGEUP",
            "arrow_down": "DOWN",
            "arrow_up": "UP",
            "arrow_left": "LEFT",
            "arrow_right": "RIGHT",
            "enter": "RETURN",
            "digit_1": "1",
            "digit_2": "2",
            "digit_3": "3",
            "digit_4": "4",
            "digit_5": "5",
            "digit_6": "6",
            "digit_7": "7",
            "digit_8": "8",
            "digit_9": "9",
        }
        effective = EffectiveBinding(
            " + ".join(allowed[modifier] for modifier in modifiers),
            key_names.get(key, key.upper()),
        )
        parsed.setdefault(action, []).append(effective)
    return parsed


def _text_value(accessible: Any) -> str:
    iface = safe_call(None, accessible.get_text_iface)
    if not iface:
        return ""
    return clean_text(safe_call("", iface.get_text, 0, -1))


def _set_text(accessible: Any, value: str) -> bool:
    iface = safe_call(None, accessible.get_editable_text_iface)
    return bool(iface and safe_call(False, iface.set_text_contents, value))


def _do_exact_action(accessible: Any, name: str) -> bool:
    action = safe_call(None, accessible.get_action_iface)
    if not action:
        return False
    names = action_names(accessible)
    for index, candidate in enumerate(names):
        if candidate == name.lower():
            return bool(safe_call(False, action.do_action, index))
    return False


def _action_attribute(accessible: Any, name: str) -> bool:
    getter = getattr(accessible, "get_attributes", None)
    if not getter:
        return False
    attributes = safe_call({}, getter)
    if isinstance(attributes, dict):
        return name in {clean_text(key) for key in attributes} | {
            clean_text(value) for value in attributes.values()
        }
    if isinstance(attributes, (list, tuple)):
        return any(name == clean_text(value) or name in clean_text(value) for value in attributes)
    return name in clean_text(attributes)


class GhosttyProvider:
    name = "ghostty"

    def __init__(self) -> None:
        self.cached = ProviderResult(self.name)
        self.has_scanned = False
        self.native_tabs: dict[str, NativeTab] = {}
        self.bindings: dict[str, list[EffectiveBinding]] = {}

    async def scan(self, context: ScanContext) -> ProviderResult:
        if not context.include_ghostty and self.has_scanned:
            return self.cached
        self.has_scanned = True
        if not any(
            GHOSTTY_CLASS.search(
                str(client.get("class") or client.get("initialClass") or "")
            )
            for client in context.hypr_clients
        ):
            self.cached = ProviderResult(self.name)
            return self.cached
        version = await context.runner.run(["ghostty", "+version"], timeout=1.0)
        version_text = version.stdout + version.stderr
        if version.returncode != 0:
            self.cached = ProviderResult(self.name, warnings=["Ghostty command is unavailable"])
            return self.cached
        if not GHOSTTY_131.search(version_text):
            self.cached = ProviderResult(
                self.name,
                warnings=["Ghostty palette integration requires the shipped 1.3.1 interface"],
            )
            return self.cached

        keybind_result = await context.runner.run(["ghostty", "+list-keybinds", "--plain"], timeout=1.2)
        self.bindings = parse_keybindings(keybind_result.stdout) if keybind_result.returncode == 0 else {}
        tree = AtspiTree()
        tops = [
            top
            for top in tree.top_levels(context, include_ghostty=True)
            if GHOSTTY_CLASS.search(str(top.client.get("class") or ""))
        ]
        if not tops:
            self.cached = ProviderResult(self.name)
            return self.cached

        previous_address = await self._active_address(context)
        items: list[Thing] = []
        warnings: list[str] = []
        surfaces: list[dict[str, Any]] = []
        tab_objects: dict[str, NativeTab] = {}
        tabs_by_pid: dict[int, list[tuple[NativeTab, str]]] = {}

        # Native tab strips remain public GTK/AT-SPI objects; pane coverage is
        # the separately capability-tested command-palette bridge.
        for top in tops:
            pid = int(top.client.get("pid") or top.pid)
            address = normalized_address(top.client.get("address"))
            birth = process_birth(pid)
            tabs = tree.native_tabs(top, browser=False)
            for ordinal, tab in enumerate(tabs):
                item_id = stable_id(self.name, pid, birth, address, "tab", tab.native_id)
                tab_objects[item_id] = tab
                tabs_by_pid.setdefault(pid, []).append((tab, item_id))
                parent = self._window_parent_id(context, address)
                items.append(
                    Thing(
                        id=item_id,
                        kind="terminal-tab",
                        provider="Ghostty",
                        title=tab.title,
                        context=top.name or "Ghostty",
                        search_terms=["ghostty", str(ordinal + 1)],
                        parent_id=parent,
                        badges=["Tab", "Native"],
                        active=tab.selected and int(top.client.get("focusHistoryID") or 0) == 0,
                        recency=3600 if tab.selected else 0,
                        activation={
                            "target": "tab",
                            "pid": pid,
                            "birth": birth,
                            "address": address,
                            "native_id": tab.native_id,
                            "tab_item_id": item_id,
                            "tab_index": ordinal,
                            "tab_count": len(tabs),
                        },
                    )
                )

        # Each process exposes every one of its surfaces from any window's
        # palette, so probe exactly one controlling top-level per PID.
        by_pid: dict[int, TopLevel] = {}
        for top in tops:
            pid = int(top.client.get("pid") or top.pid)
            by_pid.setdefault(pid, top)
        for pid, top in by_pid.items():
            address = normalized_address(top.client.get("address"))
            birth = process_birth(pid)
            try:
                fingerprints = await self._enumerate_palette(context, top)
            except CommandError as error:
                warnings.append(f"Ghostty {pid}: {error}")
                continue
            for fingerprint in fingerprints:
                item_id = stable_id(
                    self.name,
                    pid,
                    birth,
                    "surface",
                    fingerprint.title,
                    fingerprint.cwd,
                    fingerprint.occurrence,
                    fingerprint.ordinal,
                )
                parent_id, host_address = self._surface_parent(
                    context, pid, fingerprint, tabs_by_pid.get(pid, [])
                )
                activation = {
                    "target": "surface",
                    "pid": pid,
                    "birth": birth,
                    "control_address": address,
                    "host_address": host_address,
                    "fingerprint": fingerprint.json(),
                }
                items.append(
                    Thing(
                        id=item_id,
                        kind="terminal-pane",
                        provider="Ghostty",
                        title=fingerprint.title,
                        context=fingerprint.cwd or "Ghostty surface",
                        search_terms=["ghostty", fingerprint.cwd, str(fingerprint.ordinal + 1)],
                        parent_id=parent_id,
                        badges=["Surface"],
                        recency=max(0, 2500 - fingerprint.ordinal),
                        activation=activation,
                    )
                )
                surfaces.append(
                    {
                        "item_id": item_id,
                        "pid": pid,
                        "title": fingerprint.title,
                        "cwd": fingerprint.cwd,
                        "address": host_address,
                        "activation": activation,
                    }
                )

        self.native_tabs = tab_objects
        if previous_address:
            try:
                await focus_address(context, previous_address)
            except CommandError:
                pass
        self.cached = ProviderResult(self.name, items, warnings, {"surfaces": surfaces})
        return self.cached

    async def _enumerate_palette(self, context: ScanContext, top: TopLevel) -> list[PaletteFingerprint]:
        address = normalized_address(top.client.get("address"))
        await focus_address(context, address)
        await self._toggle_command_palette(context, top)
        try:
            palette = await self._wait_palette(top.application)
            if not palette or not _set_text(palette.search, FOCUS_PREFIX):
                raise CommandError("palette search is not EditableText")
            await asyncio.sleep(0.06)
            if _text_value(palette.search) != FOCUS_PREFIX:
                raise CommandError("palette query could not be verified")
            await self._send_verified_key(context, address, palette, "HOME")
            fingerprints = await self._walk_rows(context, address, palette)
            if not fingerprints:
                raise CommandError("palette exposed no Focus: rows")
            return fingerprints
        finally:
            await self._close_palette(context, address, top.application)

    async def _toggle_command_palette(self, context: ScanContext, top: TopLevel) -> None:
        action_name = "win.toggle-command-palette"
        for node in walk(top.accessible):
            accessible = node.accessible
            if action_name in action_names(accessible):
                if _do_exact_action(accessible, action_name):
                    return
                raise CommandError("win.toggle-command-palette refused activation")
            if _action_attribute(accessible, action_name):
                if invoke_accessible(accessible):
                    return
                raise CommandError("win.toggle-command-palette is not actionable")

        # GTK does not guarantee that a window GAction name is exported as an
        # AT-SPI action. The pinned release also exposes its action catalogue
        # and effective accelerator, which provides a capability-checked,
        # exact-address fallback without typing palette text into the PTY.
        actions = await context.runner.run(["ghostty", "+list-actions"], timeout=1.0)
        available = {line.strip().split(None, 1)[0] for line in actions.stdout.splitlines() if line.strip()}
        if actions.returncode != 0 or "toggle_command_palette" not in available:
            raise CommandError("win.toggle-command-palette capability is unavailable")
        keybinds = await context.runner.run(["ghostty", "+list-keybinds", "--plain"], timeout=1.2)
        bindings = parse_keybindings(keybinds.stdout) if keybinds.returncode == 0 else {}
        choices = bindings.get("toggle_command_palette", [])
        if not choices:
            raise CommandError("win.toggle-command-palette has no safe effective binding")
        await self._send_binding(
            context,
            normalized_address(top.client.get("address")),
            choices[0],
        )

    async def _walk_rows(
        self, context: ScanContext, address: str, palette: PaletteState
    ) -> list[PaletteFingerprint]:
        rows: list[PaletteFingerprint] = []
        occurrences: dict[tuple[str, str], int] = {}
        for ordinal in range(4096):
            selected = await self._wait_selected(palette)
            if not selected:
                break
            title, cwd = self._row_values(selected)
            if not title.startswith(FOCUS_PREFIX):
                raise CommandError("palette selection left the filtered Focus: rows")
            title = clean_text(title[len(FOCUS_PREFIX) :]) or "Untitled"
            key = (title, cwd)
            occurrences[key] = occurrences.get(key, 0) + 1
            fingerprint = PaletteFingerprint(title, cwd, occurrences[key], ordinal)
            rows.append(fingerprint)
            marker = self._row_marker(selected)
            await self._send_verified_key(context, address, palette, "DOWN")
            changed = await self._wait_row_change(palette, marker)
            if not changed:
                break
        return rows

    async def _send_verified_key(
        self,
        context: ScanContext,
        address: str,
        palette: PaletteState,
        key: str,
        mods: str = "",
        require_focus_filter: bool = True,
    ) -> None:
        current = self._find_palette(palette.application)
        if not current or (
            require_focus_filter and _text_value(current.search) != FOCUS_PREFIX
        ) or (
            palette.identity and current.identity != palette.identity
        ):
            raise CommandError("Ghostty palette disappeared before synthetic navigation")
        for state in ("down", "up"):
            expression = (
                "hl.dsp.send_key_state({ mods = "
                + lua_string(mods)
                + ", key = "
                + lua_string(key)
                + ", state = "
                + lua_string(state)
                + ", window = "
                + lua_string("address:" + address)
                + " })"
            )
            result = await context.runner.run(["hyprctl", "dispatch", expression], timeout=0.8)
            if result.returncode != 0 or result.stdout.strip() not in ("", "ok"):
                raise CommandError("Hyprland rejected targeted Ghostty navigation")
        await asyncio.sleep(0.035)

    async def _close_palette(
        self, context: ScanContext, address: str, application: Any
    ) -> None:
        palette = self._find_palette(application)
        if not palette:
            return
        # Cleanup is not list navigation: it is permitted before Focus: was
        # installed, but only while the modal's live EditableText and list are
        # still proven present. The key remains targeted to the exact window.
        await self._send_verified_key(
            context,
            address,
            palette,
            "ESCAPE",
            require_focus_filter=False,
        )
        for _attempt in range(16):
            if not self._find_palette(application):
                return
            await asyncio.sleep(0.025)
        raise CommandError("Ghostty command palette could not be closed safely")

    async def _send_binding(
        self, context: ScanContext, address: str, binding: EffectiveBinding
    ) -> None:
        # Standalone tab bindings are sent only after AT-SPI proves the target
        # window and current tab. Unlike palette navigation, no text key is
        # ever synthesized here unless it is present in Ghostty's effective
        # keybinding table for the requested action.
        for state in ("down", "up"):
            expression = (
                "hl.dsp.send_key_state({ mods = "
                + lua_string(binding.mods)
                + ", key = "
                + lua_string(binding.key)
                + ", state = "
                + lua_string(state)
                + ", window = "
                + lua_string("address:" + address)
                + " })"
            )
            result = await context.runner.run(["hyprctl", "dispatch", expression], timeout=0.8)
            if result.returncode != 0 or result.stdout.strip() not in ("", "ok"):
                raise CommandError("Hyprland rejected a verified Ghostty tab binding")
        await asyncio.sleep(0.05)

    async def _wait_palette(self, application: Any) -> PaletteState | None:
        for _attempt in range(30):
            palette = self._find_palette(application)
            if palette:
                return palette
            await asyncio.sleep(0.025)
        return None

    @staticmethod
    def _find_palette(application: Any) -> PaletteState | None:
        if Atspi is None:
            return None
        searches: list[Any] = []
        for node in walk(application, max_nodes=5000):
            accessible = node.accessible
            if safe_call(None, accessible.get_editable_text_iface) is not None:
                name = clean_text(safe_call("", accessible.get_name))
                description = clean_text(safe_call("", accessible.get_description))
                if "command" in (name + " " + description).lower() or _text_value(accessible).startswith(FOCUS_PREFIX):
                    searches.append(accessible)
        candidates: list[tuple[int, Any, Any, Any]] = []
        for search in searches:
            cursor = search
            seen: set[str] = set()
            for depth in range(12):
                cursor = safe_call(None, cursor.get_parent)
                if not cursor:
                    break
                marker = GhosttyProvider._accessible_marker(cursor)
                if marker in seen:
                    break
                seen.add(marker)
                cursor_role = role(cursor)
                is_modal = cursor_role in (Atspi.Role.DIALOG, Atspi.Role.ALERT) or has_state(
                    cursor, Atspi.StateType.MODAL
                )
                if not is_modal:
                    continue
                list_candidates: list[tuple[int, Any]] = []
                for descendant in walk(cursor, max_nodes=1800, max_depth=16):
                    if role(descendant.accessible) != Atspi.Role.LIST:
                        continue
                    row_count = sum(
                        1
                        for row in walk(descendant.accessible, max_nodes=800, max_depth=10)
                        if role(row.accessible) == Atspi.Role.LIST_ITEM
                    )
                    if row_count:
                        list_candidates.append((row_count, descendant.accessible))
                if list_candidates:
                    # Ghostty's virtualized command list is the modal's
                    # populated list. Reject application/window-wide pairings
                    # so terminal content can never masquerade as the palette.
                    list_candidates.sort(key=lambda value: value[0], reverse=True)
                    candidates.append((depth, search, list_candidates[0][1], cursor))
                    break
        if not candidates:
            return None
        candidates.sort(key=lambda value: value[0])
        _depth, search, list_view, container = candidates[0]
        return PaletteState(
            application,
            search,
            list_view,
            container,
            GhosttyProvider._accessible_marker(container),
        )

    @staticmethod
    def _accessible_marker(accessible: Any) -> str:
        identifier = clean_text(safe_call("", accessible.get_accessible_id))
        path = clean_text(getattr(accessible, "path", ""))
        name = clean_text(safe_call("", accessible.get_name))
        index = str(safe_call(-1, accessible.get_index_in_parent))
        return "|".join((identifier, path, str(role(accessible)), name, index))

    async def _wait_selected(self, palette: PaletteState) -> Any:
        for _attempt in range(20):
            selected = self._selected_row(palette)
            if selected:
                return selected
            await asyncio.sleep(0.02)
        return None

    @staticmethod
    def _selected_row(palette: PaletteState) -> Any:
        if Atspi is None:
            return None
        for node in walk(palette.list_view, max_nodes=1200):
            if role(node.accessible) == Atspi.Role.LIST_ITEM and has_state(
                node.accessible, Atspi.StateType.SELECTED
            ):
                return node.accessible
        return None

    async def _wait_row_change(self, palette: PaletteState, marker: str) -> bool:
        for _attempt in range(12):
            selected = self._selected_row(palette)
            if selected and self._row_marker(selected) != marker:
                return True
            await asyncio.sleep(0.018)
        return False

    @staticmethod
    def _row_marker(accessible: Any) -> str:
        identifier = clean_text(safe_call("", accessible.get_accessible_id))
        path = clean_text(getattr(accessible, "path", ""))
        index = str(safe_call(-1, accessible.get_index_in_parent))
        title, cwd = GhosttyProvider._row_values(accessible)
        return "|".join(
            (identifier, path, index, clean_text(safe_call("", accessible.get_name)), title, cwd)
        )

    @staticmethod
    def _row_values(accessible: Any) -> tuple[str, str]:
        texts: list[str] = []
        descriptions: list[str] = []
        for node in walk(accessible, max_nodes=80, max_depth=8):
            name = clean_text(safe_call("", node.accessible.get_name))
            description = clean_text(safe_call("", node.accessible.get_description))
            if name and name not in texts:
                texts.append(name)
            if description and description not in descriptions:
                descriptions.append(description)
        title = next((text for text in texts if text.startswith(FOCUS_PREFIX)), texts[0] if texts else "")
        cwd = ""
        for candidate in descriptions + texts:
            exact_path = canonical_path(candidate.rstrip(".,;:"))
            if candidate.startswith("/") and os.path.isabs(exact_path):
                cwd = exact_path
                break
            for match in re.finditer(r"(?:^|\s)(/[^\s\x00]+)", candidate):
                path = canonical_path(match.group(1).rstrip(".,;:"))
                if os.path.isabs(path):
                    cwd = path
                    break
            if cwd:
                break
        return title, cwd

    async def activate(self, activation: dict[str, Any], context: ScanContext) -> None:
        target = str(activation.get("target") or "")
        pid = int(activation.get("pid") or 0)
        if process_birth(pid) != str(activation.get("birth")):
            raise CommandError("Ghostty process was replaced")
        if target == "tab":
            await self._activate_tab(activation, context)
        elif target == "surface":
            await self._activate_surface(activation, context)
        else:
            raise CommandError("unknown Ghostty activation target")

    async def _activate_tab(self, activation: dict[str, Any], context: ScanContext) -> None:
        item_id = str(activation.get("item_id") or activation.get("tab_item_id") or "")
        tab = self.native_tabs.get(item_id)
        if not tab or (Atspi is not None and has_state(tab.accessible, Atspi.StateType.DEFUNCT)):
            raise CommandError("Ghostty native tab closed")
        address = normalized_address(activation.get("address"))
        await focus_address(context, address)
        if Atspi is not None and has_state(tab.accessible, Atspi.StateType.SELECTED):
            return
        result = await context.runner.run(["ghostty", "+list-keybinds", "--plain"], timeout=1.2)
        bindings = parse_keybindings(result.stdout) if result.returncode == 0 else {}
        index = int(activation.get("tab_index") or 0)
        count = int(activation.get("tab_count") or 0)
        direct_action = f"goto_tab:{index + 1}"
        direct = bindings.get(direct_action, [])
        if not direct and index == count - 1:
            direct = bindings.get("last_tab", [])
        if direct:
            await self._send_binding(context, address, direct[0])
        else:
            selected_index = self._selected_tab_index(tab.top)
            next_binding = bindings.get("next_tab", [])
            if selected_index < 0 or not next_binding or count <= 0:
                raise CommandError("Ghostty has no verified effective binding for this tab")
            steps = (index - selected_index) % count
            for _step in range(steps):
                before = self._selected_tab_index(tab.top)
                await self._send_binding(context, address, next_binding[0])
                after = self._selected_tab_index(tab.top)
                if after < 0 or after == before:
                    raise CommandError("Ghostty tab selection did not follow its effective binding")
        for _attempt in range(15):
            if has_state(tab.accessible, Atspi.StateType.SELECTED):
                await focus_address(context, address)
                return
            await asyncio.sleep(0.025)
        raise CommandError("Ghostty did not select the requested native tab")

    @staticmethod
    def _selected_tab_index(top: TopLevel) -> int:
        tree = AtspiTree()
        tabs = tree.native_tabs(top, browser=False)
        return next((index for index, tab in enumerate(tabs) if tab.selected), -1)

    async def _activate_surface(self, activation: dict[str, Any], context: ScanContext) -> None:
        pid = int(activation.get("pid") or 0)
        control_address = normalized_address(activation.get("control_address"))
        tree = AtspiTree()
        tops = [
            top
            for top in tree.top_levels(context, include_ghostty=True)
            if int(top.client.get("pid") or top.pid) == pid
        ]
        top = next(
            (top for top in tops if normalized_address(top.client.get("address")) == control_address),
            tops[0] if len(tops) == 1 else None,
        )
        if not top:
            raise CommandError("Ghostty control window is ambiguous")
        address = normalized_address(top.client.get("address"))
        await focus_address(context, address)
        await self._toggle_command_palette(context, top)
        presented = False
        try:
            palette = await self._wait_palette(top.application)
            if not palette or not _set_text(palette.search, FOCUS_PREFIX):
                raise CommandError("Ghostty palette could not be prepared")
            await asyncio.sleep(0.06)
            await self._send_verified_key(context, address, palette, "HOME")
            rows = await self._walk_rows(context, address, palette)
            expected_value = activation.get("fingerprint")
            expected = PaletteFingerprint(
                clean_text(expected_value.get("title")) if isinstance(expected_value, dict) else "",
                canonical_path(str(expected_value.get("cwd") or "")) if isinstance(expected_value, dict) else "",
                int(expected_value.get("occurrence") or 0) if isinstance(expected_value, dict) else 0,
                int(expected_value.get("ordinal") or -1) if isinstance(expected_value, dict) else -1,
            )
            if expected.ordinal < 0 or expected.ordinal >= len(rows) or rows[expected.ordinal] != expected:
                raise CommandError("Ghostty surface fingerprint changed")

            # _walk_rows stops at the final row. Rewind, then prove every step
            # lands on the revalidated fingerprint before Enter is delivered.
            await self._send_verified_key(context, address, palette, "HOME")
            for ordinal in range(expected.ordinal + 1):
                selected = await self._wait_selected(palette)
                if not selected:
                    raise CommandError("Ghostty palette lost its selected row")
                title, cwd = self._row_values(selected)
                title = clean_text(title[len(FOCUS_PREFIX) :]) if title.startswith(FOCUS_PREFIX) else title
                if title != rows[ordinal].title or cwd != rows[ordinal].cwd:
                    raise CommandError("Ghostty palette mutated during activation")
                if ordinal < expected.ordinal:
                    await self._send_verified_key(context, address, palette, "DOWN")
            await self._send_verified_key(context, address, palette, "RETURN")
            for _attempt in range(16):
                if not self._find_palette(top.application):
                    presented = True
                    break
                await asyncio.sleep(0.025)
            if not presented:
                raise CommandError("Ghostty surface action did not close its palette")
        finally:
            if not presented:
                await self._close_palette(context, address, top.application)

        host_address = normalized_address(activation.get("host_address"))
        client = context.client_by_address(host_address) if host_address else None
        if not client or int(client.get("pid") or 0) != pid:
            host_address = await self._active_address_for_pid(context, pid)
        if host_address:
            await focus_address(context, host_address)

    @staticmethod
    async def _active_address(context: ScanContext) -> str:
        result = await context.runner.run(["hyprctl", "-j", "activewindow"], timeout=0.6)
        if result.returncode != 0:
            return ""
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError:
            return ""
        return normalized_address(value.get("address")) if isinstance(value, dict) else ""

    @staticmethod
    async def _active_address_for_pid(context: ScanContext, pid: int) -> str:
        for _attempt in range(15):
            result = await context.runner.run(["hyprctl", "-j", "activewindow"], timeout=0.6)
            if result.returncode == 0:
                try:
                    value = json.loads(result.stdout)
                except json.JSONDecodeError:
                    value = {}
                if isinstance(value, dict) and int(value.get("pid") or 0) == pid:
                    return normalized_address(value.get("address"))
            await asyncio.sleep(0.03)
        return ""

    @staticmethod
    def _window_parent_id(context: ScanContext, address: str) -> str:
        for client in context.provider_metadata.get("hyprland", {}).get("clients", []):
            if normalized_address(client.get("address")) == address:
                return str(client.get("item_id") or "")
        return ""

    @staticmethod
    def _surface_parent(
        context: ScanContext,
        pid: int,
        fingerprint: PaletteFingerprint,
        tabs: list[tuple[NativeTab, str]],
    ) -> tuple[str, str]:
        title_matches = [(tab, item_id) for tab, item_id in tabs if folded(tab.title) == folded(fingerprint.title)]
        if len(title_matches) == 1:
            tab, item_id = title_matches[0]
            return item_id, normalized_address(tab.top.client.get("address"))
        clients = context.clients_for_pid(pid)
        client_matches = [client for client in clients if folded(client.get("title")) == folded(fingerprint.title)]
        if len(client_matches) == 1:
            address = normalized_address(client_matches[0].get("address"))
            return GhosttyProvider._window_parent_id(context, address), address
        if len(clients) == 1:
            address = normalized_address(clients[0].get("address"))
            return GhosttyProvider._window_parent_id(context, address), address
        return "", ""
