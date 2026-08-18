from __future__ import annotations

import asyncio
import re
import threading
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from ..commands import CommandError
from ..model import Thing, process_birth, stable_id
from .base import ProviderResult, ScanContext, normalized_address
from .hyprland import focus_address

try:
    import gi

    gi.require_version("Atspi", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Atspi, GLib
except (ImportError, ValueError):  # Covered as an isolated provider warning.
    Atspi = None  # type: ignore[assignment]
    GLib = None  # type: ignore[assignment]


BROWSER_CLASS = re.compile(
    r"(?:^|[._-])(?:chromium|google-chrome|chrome|brave(?:-browser)?|microsoft-edge|"
    r"firefox|zen|vivaldi|helium|librewolf)(?=$|[._-])",
    re.IGNORECASE,
)
GHOSTTY_CLASS = re.compile(r"(?:com\.mitchellh\.ghostty|ghostty)", re.IGNORECASE)
REJECTED_STRIP_NAME = re.compile(r"(?:dock|tool|sidebar|side panel|developer tools|inspector)", re.IGNORECASE)


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\x00", " ")
    return " ".join(text.split()).strip()


def folded(value: Any) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", clean_text(value).lower())
        if not unicodedata.combining(character)
    )


def safe_call(default: Any, function: Callable[..., Any], *args: Any) -> Any:
    try:
        return function(*args)
    except Exception:
        return default


def role(accessible: Any) -> Any:
    return safe_call(None, accessible.get_role)


def states(accessible: Any) -> Any:
    return safe_call(None, accessible.get_state_set)


def has_state(accessible: Any, state: Any) -> bool:
    current = states(accessible)
    return bool(current and safe_call(False, current.contains, state))


def children(accessible: Any, limit: int = 10000) -> list[Any]:
    count = int(safe_call(0, accessible.get_child_count) or 0)
    return [
        child
        for index in range(min(count, limit))
        if (child := safe_call(None, accessible.get_child_at_index, index)) is not None
    ]


@dataclass(slots=True)
class Node:
    accessible: Any
    path: tuple[int, ...]
    depth: int
    inside_document: bool
    ancestors: tuple[Any, ...]


def walk(root: Any, *, max_nodes: int = 6000, max_depth: int = 24) -> Iterator[Node]:
    if Atspi is None:
        return
    document_roles = {
        Atspi.Role.DOCUMENT_EMAIL,
        Atspi.Role.DOCUMENT_FRAME,
        Atspi.Role.DOCUMENT_PRESENTATION,
        Atspi.Role.DOCUMENT_SPREADSHEET,
        Atspi.Role.DOCUMENT_TEXT,
        Atspi.Role.DOCUMENT_WEB,
    }
    stack: list[Node] = [Node(root, (), 0, False, ())]
    visited = 0
    while stack and visited < max_nodes:
        node = stack.pop()
        visited += 1
        yield node
        if node.depth >= max_depth or has_state(node.accessible, Atspi.StateType.DEFUNCT):
            continue
        node_role = role(node.accessible)
        inside_document = node.inside_document or node_role in document_roles
        descendants = children(node.accessible)
        for index in range(len(descendants) - 1, -1, -1):
            stack.append(
                Node(
                    descendants[index],
                    node.path + (index,),
                    node.depth + 1,
                    inside_document,
                    node.ancestors + (node_role,),
                )
            )


def action_names(accessible: Any) -> list[str]:
    action = safe_call(None, accessible.get_action_iface)
    if not action:
        return []
    count = int(safe_call(0, action.get_n_actions) or 0)
    return [clean_text(safe_call("", action.get_action_name, index)).lower() for index in range(count)]


def invoke_accessible(accessible: Any, preferred: Iterable[str] = ("activate", "click", "press", "select")) -> bool:
    action = safe_call(None, accessible.get_action_iface)
    if action:
        names = action_names(accessible)
        for wanted in preferred:
            for index, name in enumerate(names):
                if wanted == name or wanted in name:
                    return bool(safe_call(False, action.do_action, index))
    component = safe_call(None, accessible.get_component_iface)
    return bool(component and safe_call(False, component.grab_focus))


def accessible_id(accessible: Any, fallback: str) -> str:
    value = clean_text(safe_call("", accessible.get_accessible_id))
    if value:
        return value
    path = clean_text(getattr(accessible, "path", ""))
    return path or fallback


@dataclass(slots=True)
class TopLevel:
    application: Any
    accessible: Any
    pid: int
    index: int
    name: str
    client: dict[str, Any]


@dataclass(slots=True)
class NativeTab:
    accessible: Any
    top: TopLevel
    strip_path: tuple[int, ...]
    tab_path: tuple[int, ...]
    index: int
    title: str
    selected: bool
    native_id: str


class AtspiTree:
    def __init__(self) -> None:
        if Atspi is None:
            raise CommandError("PyGObject AT-SPI bindings are unavailable")
        result = safe_call(-1, Atspi.init)
        # libatspi returns 1 when another in-process caller (our event monitor)
        # has already initialized the singleton; only a negative value fails.
        if isinstance(result, int) and result < 0:
            raise CommandError("AT-SPI initialization failed")

    def applications(self) -> list[Any]:
        desktop = safe_call(None, Atspi.get_desktop, 0)
        return children(desktop) if desktop else []

    def top_levels(self, context: ScanContext, *, include_ghostty: bool = False) -> list[TopLevel]:
        out: list[TopLevel] = []
        for application in self.applications():
            pid = int(safe_call(0, application.get_process_id) or 0)
            candidates = context.clients_for_pid(pid)
            if not candidates:
                # Some toolkits expose an app-side helper PID. Match only when
                # it has exactly one managed ancestor, never by a loose title.
                ancestors = context.processes.ancestors(pid)
                managed_pids = {int(client.get("pid") or 0) for client in context.hypr_clients}
                ancestor = next((process.pid for process in ancestors if process.pid in managed_pids), None)
                candidates = context.clients_for_pid(ancestor or 0)
            if not candidates:
                continue
            for top_index, top in enumerate(children(application)):
                top_name = clean_text(safe_call("", top.get_name))
                matched = self._match_client(top_name, candidates)
                if not matched:
                    continue
                if not include_ghostty and GHOSTTY_CLASS.search(str(matched.get("class") or "")):
                    continue
                out.append(TopLevel(application, top, pid, top_index, top_name, matched))
        return out

    @staticmethod
    def _match_client(top_name: str, clients: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(clients) == 1:
            return clients[0]
        wanted = folded(top_name)
        exact = [client for client in clients if folded(client.get("title")) == wanted and wanted]
        if len(exact) == 1:
            return exact[0]
        contained = [
            client
            for client in clients
            if wanted and (wanted in folded(client.get("title")) or folded(client.get("title")) in wanted)
        ]
        return contained[0] if len(contained) == 1 else None

    def native_tabs(self, top: TopLevel, *, browser: bool, strict_generic: bool = True) -> list[NativeTab]:
        candidates: list[tuple[Node, list[tuple[int, Any]]]] = []
        for node in walk(top.accessible):
            if node.inside_document or role(node.accessible) != Atspi.Role.PAGE_TAB_LIST:
                continue
            strip_name = clean_text(safe_call("", node.accessible.get_name))
            if REJECTED_STRIP_NAME.search(strip_name):
                continue
            tabs = [
                (index, child)
                for index, child in enumerate(children(node.accessible))
                if role(child) == Atspi.Role.PAGE_TAB
            ]
            if not tabs:
                continue
            if strict_generic and not browser and node.depth > 8:
                continue
            actionable = sum(
                1
                for _, tab in tabs
                if action_names(tab) or safe_call(None, tab.get_component_iface) is not None
            )
            if actionable != len(tabs):
                continue
            candidates.append((node, tabs))
        if not candidates:
            return []

        # A browser's primary strip has the most real page tabs. Depth is only
        # the tie-breaker, preserving vertical/custom tab-strip layouts.
        candidates.sort(key=lambda candidate: (-len(candidate[1]), candidate[0].depth, candidate[0].path))
        node, tabs = candidates[0]
        result: list[NativeTab] = []
        occurrences: dict[str, int] = {}
        for tab_index, accessible in tabs:
            title = clean_text(safe_call("", accessible.get_name)) or "Untitled tab"
            key = folded(title)
            occurrences[key] = occurrences.get(key, 0) + 1
            occurrence = occurrences[key]
            native = accessible_id(accessible, ".".join(map(str, node.path + (tab_index,))))
            result.append(
                NativeTab(
                    accessible=accessible,
                    top=top,
                    strip_path=node.path,
                    tab_path=node.path + (tab_index,),
                    index=tab_index,
                    title=title,
                    selected=has_state(accessible, Atspi.StateType.SELECTED),
                    native_id=native + f":{occurrence}",
                )
            )
        return result


class AtspiEventMonitor:
    EVENT_TYPES = (
        "object:children-changed",
        "object:property-change:accessible-name",
        "object:state-changed:selected",
        "window:activate",
        "window:create",
        "window:destroy",
    )

    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.listener: Any = None
        self.loop: Any = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if Atspi is None or GLib is None or self.thread:
            return

        def run() -> None:
            safe_call(None, Atspi.init)
            self.listener = Atspi.EventListener.new(lambda _event: self.callback())
            for event_type in self.EVENT_TYPES:
                safe_call(False, self.listener.register, event_type)
            self.loop = GLib.MainLoop()
            self.loop.run()
            for event_type in self.EVENT_TYPES:
                safe_call(False, self.listener.deregister, event_type)

        self.thread = threading.Thread(target=run, name="everything-atspi-events", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.loop:
            safe_call(None, self.loop.quit)
        if self.thread:
            self.thread.join(timeout=1.0)
        self.thread = None
        self.loop = None
        self.listener = None


class AtspiProvider:
    name = "atspi"

    def __init__(self) -> None:
        self.objects: dict[str, NativeTab] = {}

    async def scan(self, context: ScanContext) -> ProviderResult:
        return await asyncio.to_thread(self._scan_sync, context)

    def _scan_sync(self, context: ScanContext) -> ProviderResult:
        tree = AtspiTree()
        objects: dict[str, NativeTab] = {}
        items: list[Thing] = []
        top_levels = tree.top_levels(context)
        for top in top_levels:
            app_class = str(top.client.get("class") or top.client.get("initialClass") or "")
            is_browser = bool(BROWSER_CLASS.search(app_class))
            tabs = tree.native_tabs(top, browser=is_browser)
            if not tabs:
                continue
            address = normalized_address(top.client.get("address"))
            pid = int(top.client.get("pid") or top.pid)
            birth = process_birth(pid)
            parent = self._window_parent_id(context, address)
            active_window = int(top.client.get("focusHistoryID") or 0) == 0
            kind = "browser-tab" if is_browser else "app-tab"
            provider_name = self._provider_name(app_class, is_browser)
            for tab in tabs:
                item_id = stable_id(self.name, pid, birth, address, tab.native_id)
                objects[item_id] = tab
                items.append(
                    Thing(
                        id=item_id,
                        kind=kind,
                        provider=provider_name,
                        title=tab.title,
                        context=f"{top.name or app_class} · native tab",
                        search_terms=[app_class, top.name],
                        parent_id=parent,
                        badges=["Tab", "Title only" if is_browser else "Native"],
                        active=active_window and tab.selected,
                        recency=3500 if active_window and tab.selected else 0,
                        activation={
                            "address": address,
                            "pid": pid,
                            "birth": birth,
                            "native_id": tab.native_id,
                        },
                    )
                )
        self.objects = objects
        return ProviderResult(self.name, items)

    @staticmethod
    def _provider_name(app_class: str, browser: bool) -> str:
        value = app_class.lower()
        if not browser:
            return "Application"
        for needle, label in (
            ("librewolf", "LibreWolf"),
            ("firefox", "Firefox"),
            ("zen", "Zen"),
            ("brave", "Brave"),
            ("edge", "Edge"),
            ("vivaldi", "Vivaldi"),
            ("helium", "Helium"),
            ("chrome", "Chrome"),
            ("chromium", "Chromium"),
        ):
            if needle in value:
                return label
        return "Browser"

    @staticmethod
    def _window_parent_id(context: ScanContext, address: str) -> str:
        for client in context.provider_metadata.get("hyprland", {}).get("clients", []):
            if normalized_address(client.get("address")) == address:
                return str(client.get("item_id") or "")
        return ""

    async def activate(self, activation: dict[str, Any], context: ScanContext) -> None:
        item_id = str(activation.get("item_id") or "")
        tab = self.objects.get(item_id)
        if not tab:
            # Discovery stores item_id only in the registry activation wrapper;
            # callers normally inject it before dispatch. Fall back to the
            # stable native fingerprint for a just-refreshed provider.
            native_id = str(activation.get("native_id") or "")
            tab = next((value for value in self.objects.values() if value.native_id == native_id), None)
        if not tab or has_state(tab.accessible, Atspi.StateType.DEFUNCT):
            raise CommandError("native tab is no longer available")
        pid = int(activation.get("pid") or 0)
        if process_birth(pid) != str(activation.get("birth")):
            raise CommandError("native tab process was replaced")
        address = str(activation.get("address") or "")
        client = context.client_by_address(address)
        if not client or int(client.get("pid") or 0) != pid:
            raise CommandError("native tab window is no longer managed")
        if not await asyncio.to_thread(invoke_accessible, tab.accessible):
            raise CommandError("native tab did not expose an activation action")
        await focus_address(context, address)
