import gi

try:
    gi.require_version("Gtk", "4.0")
except (ValueError, AttributeError):
    pass

from gi.repository import Gtk, Gio, GLib
from .common import (
    _all_widgets,
    _find_slot_stack,
    _find_tab_view,
    _is_nautilus_window,
    find_first_by_type_name,
    log,
    schedule_slot_init,
    watch_slots,
)
from .nautilus_prefs import NautilusPrefs
from .file_view_menu import inject_view_switcher
from .compact_view import CompactListView

FILES_VIEW_TYPES = ("NautilusFilesView", "NautilusListBase")


class SlotAttachment:
    """Manages the non-destructive CompactListView inside a single NautilusWindowSlot's GtkStack."""

    def __init__(self, window: Gtk.Window, slot: Gtk.Widget, stack: Gtk.Stack, prefs: NautilusPrefs, controller):
        self.window = window
        self.slot = slot
        self.stack = stack
        self.prefs = prefs
        self.controller = controller
        self.compact_view = CompactListView(window, prefs)
        self.is_active = False
        self._reasserting = False
        self._previous_child = None

        # Cache the initial visible child before adding compact_view
        current = self.stack.get_visible_child()
        if current is not None and current is not self.compact_view:
            self._previous_child = current

        self.stack.add_named(self.compact_view, "compact-list")

        files_view = find_first_by_type_name(self.slot, FILES_VIEW_TYPES)
        if files_view is not None:
            self.compact_view.bind_native_view(files_view)

        if hasattr(self.slot, "find_property") and self.slot.find_property("location") is not None:
            self.slot.connect("notify::location", self._on_location_changed)

        self.stack.connect("notify::visible-child", self._on_visible_child_changed)

    def set_compact_active(self, active: bool):
        self.is_active = active
        log(f"SlotAttachment.set_compact_active: active={active}, slot={self.slot}")
        if active:
            current = self.stack.get_visible_child()
            if current is not None and current is not self.compact_view:
                self._previous_child = current
            loc = self.get_slot_location()
            if loc is not None and not self._is_special_uri(loc.get_uri()):
                self.compact_view.load_location(loc)
                self.stack.set_visible_child(self.compact_view)
                return

        # Restore native view using cached widget pointer
        target = self._previous_child
        if target is None or (hasattr(target, "get_parent") and target.get_parent() is not self.stack):
            target = self.stack.get_first_child()
            if target is self.compact_view and hasattr(target, "get_next_sibling"):
                target = target.get_next_sibling()

        if target is not None:
            log(f"SlotAttachment.set_compact_active(False): restoring native child {target}")
            self.stack.set_visible_child(target)
        else:
            log("SlotAttachment.set_compact_active(False): no native target child found")

    def get_slot_location(self) -> Gio.File | None:
        if self.slot is not None and hasattr(self.slot, "find_property") and self.slot.find_property("location") is not None:
            return self.slot.get_property("location")
        return None

    @staticmethod
    def _is_special_uri(uri: str) -> bool:
        return uri.startswith(
            ("recent:", "starred:", "trash:", "network:", "x-nautilus-search:")
        )

    def _on_location_changed(self, _slot, _pspec):
        files_view = find_first_by_type_name(self.slot, FILES_VIEW_TYPES)
        if files_view is not None:
            self.compact_view.bind_native_view(files_view)

        if self.is_active:
            loc = self.get_slot_location()
            if loc is not None and not self._is_special_uri(loc.get_uri()):
                self.compact_view.load_location(loc)
                self.stack.set_visible_child(self.compact_view)
            else:
                target = self._previous_child or self.stack.get_first_child()
                if target is not None:
                    self.stack.set_visible_child(target)

    def _on_visible_child_changed(self, stack, _pspec):
        if self._reasserting or not self.is_active:
            return
        visible = stack.get_visible_child()
        if visible is self.compact_view:
            return
        if stack.get_visible_child_name() == "global_search_page":
            return
        loc = self.get_slot_location()
        if loc is not None and self._is_special_uri(loc.get_uri()):
            return

        self._reasserting = True
        stack.set_visible_child(self.compact_view)
        self._reasserting = False


class CompactListExtensionController:
    """Coordinates window discovery, headerbar view switcher injection, and slot attachments."""

    def __init__(self):
        self._prefs = NautilusPrefs(on_changed_cb=self._on_prefs_changed)
        self._windows: dict[int, dict] = {}
        self._window_slots: dict[int, list[SlotAttachment]] = {}

        app = Gtk.Application.get_default() or Gio.Application.get_default()
        if app is not None and hasattr(app, "connect"):
            app.connect("window-added", self._on_window_added)

        self._check_new_windows()
        GLib.timeout_add(1000, self._periodic_sync)

    def _periodic_sync(self) -> bool:
        self._check_new_windows()
        return GLib.SOURCE_CONTINUE

    def sync_windows(self):
        self._check_new_windows()
        return GLib.SOURCE_REMOVE

    def _check_new_windows(self):
        toplevels = Gtk.Window.list_toplevels()
        for win in toplevels:
            if _is_nautilus_window(win) and id(win) not in self._windows:
                self._schedule_window_init(win)

    def _on_window_added(self, _app, win: Gtk.Window):
        if _is_nautilus_window(win) and id(win) not in self._windows:
            self._schedule_window_init(win)

    def _schedule_window_init(self, win: Gtk.Window) -> None:
        win_id = id(win)
        if win_id in self._windows or not _is_nautilus_window(win):
            return
        log(f"Detected Nautilus window {win} (title={win.get_title()!r}), scheduling init...")
        attempts = [0]

        def _try():
            if win_id in self._windows:
                return GLib.SOURCE_REMOVE
            attempts[0] += 1
            title = win.get_title() or ""
            if attempts[0] <= 50 and (not win.get_mapped() or "Loading" in title or "…" in title):
                return GLib.SOURCE_CONTINUE
            log(f"Window {win} settled after {attempts[0]} attempts, running _init_window...")
            GLib.idle_add(self._init_window, win, priority=GLib.PRIORITY_LOW)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(20, _try)

    def _init_window(self, win: Gtk.Window) -> bool:
        win_id = id(win)
        if win_id in self._windows or not _is_nautilus_window(win):
            return GLib.SOURCE_REMOVE

        log(f"_init_window: setting up window {win}")
        is_compact = self._prefs.compact_view_enabled
        self._windows[win_id] = {
            "window": win,
            "is_compact": is_compact,
            "switcher": None,
            "split_button": None,
            "options_btn": None,
        }
        self._window_slots[win_id] = []

        win.connect("destroy", self._on_window_destroyed)

        self._try_inject_switcher(win)
        watch_slots(win, self._hook_slot)

        tab_view = _find_tab_view(win)
        if tab_view is not None and hasattr(tab_view, "connect"):
            tab_view.connect("notify::selected-page", lambda *_a: self.sync_view_switcher(win))

        return GLib.SOURCE_REMOVE

    def _try_inject_switcher(self, win: Gtk.Window, attempt: int = 0) -> bool:
        if id(win) not in self._windows:
            return GLib.SOURCE_REMOVE
        if inject_view_switcher(self, win):
            log(f"_try_inject_switcher: switcher injection succeeded on attempt {attempt}")
            return GLib.SOURCE_REMOVE
        if attempt < 25:
            GLib.timeout_add(60, self._try_inject_switcher, win, attempt + 1)
        else:
            log(f"_try_inject_switcher: gave up after {attempt} attempts for window {win}")
        return GLib.SOURCE_REMOVE

    def _on_window_destroyed(self, win: Gtk.Window):
        win_id = id(win)
        self._windows.pop(win_id, None)
        self._window_slots.pop(win_id, None)

    def _hook_slot(self, win: Gtk.Window, slot: Gtk.Widget):
        if slot is None:
            return
        schedule_slot_init(
            slot,
            "_compact_slot_injected",
            lambda s: self._inject_slot(win, s),
        )

    def _inject_slot(self, win: Gtk.Window, slot: Gtk.Widget):
        if slot is None:
            return
        stack = _find_slot_stack(slot)
        if stack is None:
            log(f"_inject_slot: no GtkStack found in slot {slot}")
            return

        win_id = id(win)
        if win_id not in self._window_slots:
            self._window_slots[win_id] = []

        # Check if already injected
        for existing in self._window_slots[win_id]:
            if existing.slot == slot or existing.stack == stack:
                return

        log(f"_inject_slot: attaching CompactListView to slot {slot}")
        att = SlotAttachment(win, slot, stack, self._prefs, self)
        self._window_slots[win_id].append(att)

        state = self._windows.get(win_id)
        is_compact = state.get("is_compact", self._prefs.compact_view_enabled) if state else self._prefs.compact_view_enabled
        if is_compact:
            log("_inject_slot: setting slot compact active=True (persisted enabled)")
            att.set_compact_active(True)

    def register_switcher(self, win: Gtk.Window, switcher, split_button, options_btn):
        win_id = id(win)
        state = self._windows.get(win_id)
        if state is not None:
            state["switcher"] = switcher
            state["split_button"] = split_button
            state["options_btn"] = options_btn

    def on_view_segment_activated(self, win: Gtk.Window, name: str):
        win_id = id(win)
        state = self._windows.get(win_id)
        log(f"on_view_segment_activated: name={name}, win_id={win_id}")
        if state is None or name is None:
            return

        split_button = state.get("split_button")
        native_icon = split_button.get_icon_name() if split_button is not None else None
        # When sitting on List, split button icon shows Grid ("view-grid-symbolic")
        native_on_list = (native_icon == "view-grid-symbolic")
        log(f"on_view_segment_activated: native_icon={native_icon}, native_on_list={native_on_list}")

        if name == "compact":
            self.set_window_compact_active(win, True)
        elif name == "grid":
            self.set_window_compact_active(win, False)
            if native_on_list:
                log("on_view_segment_activated: toggling native view mode to Grid")
                if not win.activate_action("slot.files-view-mode-toggle", None):
                    if split_button is not None and hasattr(split_button, "emit"):
                        split_button.emit("clicked")
        elif name == "list":
            self.set_window_compact_active(win, False)
            if not native_on_list:
                log("on_view_segment_activated: toggling native view mode to List")
                if not win.activate_action("slot.files-view-mode-toggle", None):
                    if split_button is not None and hasattr(split_button, "emit"):
                        split_button.emit("clicked")

        self.sync_view_switcher(win)

    def set_window_compact_active(self, win: Gtk.Window, active: bool):
        win_id = id(win)
        log(f"set_window_compact_active: win={win}, active={active}")
        state = self._windows.get(win_id)
        if state is not None:
            state["is_compact"] = active
        self._prefs.compact_view_enabled = active

        slots = self._window_slots.get(win_id, [])
        log(f"set_window_compact_active: updating {len(slots)} slots")
        for att in slots:
            att.set_compact_active(active)

    def sync_view_switcher(self, win: Gtk.Window):
        state = self._windows.get(id(win))
        if state is None:
            return
        switcher = state.get("switcher")
        split_button = state.get("split_button")
        if switcher is None:
            return

        is_compact = state.get("is_compact", self._prefs.compact_view_enabled)
        if is_compact:
            switcher.set_active_name("compact")
        else:
            native_icon = split_button.get_icon_name() if split_button is not None else None
            active = "list" if native_icon == "view-grid-symbolic" else "grid"
            switcher.set_active_name(active)

    def is_window_compact_enabled(self, win: Gtk.Window) -> bool:
        state = self._windows.get(id(win))
        if state is not None:
            return state.get("is_compact", self._prefs.compact_view_enabled)
        return self._prefs.compact_view_enabled

    def _on_prefs_changed(self, key: str):
        if key in ("max-column-width-chars", "shortening-mode", "icon-size"):
            for slots in self._window_slots.values():
                for att in slots:
                    if att.compact_view.get_visible():
                        att.compact_view._update_zoom_metrics()
                        att.compact_view.rebuild_columns()
