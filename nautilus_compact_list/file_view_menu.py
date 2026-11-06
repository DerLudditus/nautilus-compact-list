import os
import gi

try:
    gi.require_version("Gtk", "4.0")
except (ValueError, AttributeError):
    pass

try:
    gi.require_version("Adw", "1")
    from gi.repository import Adw
except (ValueError, AttributeError):
    Adw = None

from gi.repository import Gtk, Gdk, Gio, GLib, GObject
from .common import (
    _all_widgets,
    _find_widget,
    ensure_resources_loaded,
    get_compact_icon,
    is_bin,
    is_split_button,
    log,
)

_NATIVE_TOGGLE_ACTION = "slot.files-view-mode-toggle"

_DEFAULT_SEGMENTS = (
    ("grid", "view-grid-symbolic", "Grid View"),
    ("list", "view-list-symbolic", "List View"),
    ("compact", "view-compact-symbolic", "Compact List"),
)


class CompactListToggleButton(Gtk.Box):
    """Dynamic 3-segment switcher: flat Gtk.ToggleButtons in a light pill,
    with 1px separators that hide whenever adjacent buttons are active or hovered.
    Renders identically across GNOME 43 through GNOME 51."""

    __gtype_name__ = "CompactListToggleButton"
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, segments=None, height: int = -1) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=1)
        self.add_css_class("mc-toggle-group")
        self.set_size_request(-1, height)
        self.set_valign(Gtk.Align.FILL)

        self._buttons: dict[str, Gtk.ToggleButton] = {}
        self._hovered: dict[str, bool] = {}
        self._separators: list[Gtk.Separator] = []
        self._order: list[str] = []
        self._active_name: str | None = None
        self._syncing = False

        if segments is None:
            segments = [
                ("grid", "view-grid-symbolic", "Grid View"),
                ("list", "view-list-symbolic", "List View"),
                ("compact", get_compact_icon(), "Compact List"),
            ]

        first_btn = None
        for i, (name, icon, tooltip) in enumerate(segments):
            if i > 0:
                sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
                sep.add_css_class("mc-toggle-sep")
                sep.set_margin_top(6)
                sep.set_margin_bottom(6)
                self.append(sep)
                self._separators.append(sep)

            btn = Gtk.ToggleButton(child=self._make_segment_image(icon), tooltip_text=tooltip)
            btn.add_css_class("flat")
            btn.add_css_class("mc-toggle-btn")
            if first_btn is None:
                first_btn = btn
            else:
                btn.set_group(first_btn)
            btn.connect("toggled", self._on_button_toggled, name)

            motion = Gtk.EventControllerMotion()
            motion.connect("enter", self._on_button_enter, name)
            motion.connect("leave", self._on_button_leave, name)
            btn.add_controller(motion)

            self.append(btn)
            self._buttons[name] = btn
            self._hovered[name] = False
            self._order.append(name)

        self._update_separators()

    @staticmethod
    def _make_segment_image(icon) -> Gtk.Image:
        if isinstance(icon, Gio.Icon):
            image = Gtk.Image.new_from_gicon(icon)
        elif isinstance(icon, str):
            display = Gdk.Display.get_default()
            if display is not None:
                theme = Gtk.IconTheme.get_for_display(display)
                if not theme.has_icon(icon) and icon == "view-compact-symbolic":
                    image = Gtk.Image.new_from_gicon(get_compact_icon())
                else:
                    image = Gtk.Image.new_from_icon_name(icon)
            else:
                image = Gtk.Image.new_from_icon_name(icon)
        else:
            image = Gtk.Image.new_from_icon_name("image-missing-symbolic")

        image.set_pixel_size(-1)
        image.set_margin_start(8)
        image.set_margin_end(8)
        image.set_valign(Gtk.Align.CENTER)
        image.set_halign(Gtk.Align.CENTER)
        return image

    def _on_button_enter(self, _ctrl, _x, _y, name: str) -> None:
        self._hovered[name] = True
        self._update_separators()

    def _on_button_leave(self, _ctrl, name: str) -> None:
        self._hovered[name] = False
        self._update_separators()

    def _on_button_toggled(self, btn: Gtk.ToggleButton, name: str) -> None:
        if self._syncing or not btn.get_active():
            return
        self._active_name = name
        self._update_separators()
        self.emit("changed", name)

    def _update_separators(self) -> None:
        for i, sep in enumerate(self._separators):
            left, right = self._order[i], self._order[i + 1]
            hidden = (
                self._active_name in (left, right)
                or self._hovered.get(left)
                or self._hovered.get(right)
            )
            if hidden:
                sep.add_css_class("mc-toggle-sep-hidden")
            else:
                sep.remove_css_class("mc-toggle-sep-hidden")

    def get_active_name(self) -> str | None:
        return self._active_name

    def set_active_name(self, name: str) -> None:
        btn = self._buttons.get(name)
        if btn is None or btn.get_active():
            self._active_name = name
            self._update_separators()
            return
        self._syncing = True
        try:
            btn.set_active(True)
        finally:
            self._syncing = False
        self._active_name = name
        self._update_separators()

    def set_segment_enabled(self, name: str, enabled: bool) -> None:
        btn = self._buttons.get(name)
        if btn is not None:
            btn.set_sensitive(enabled)

    def set_segment_icon(self, name: str, icon) -> None:
        btn = self._buttons.get(name)
        if btn is not None:
            btn.set_child(self._make_segment_image(icon))


def find_sort_button(win: Gtk.Window) -> Gtk.MenuButton | None:
    """Finds the GtkMenuButton inside NautilusViewControls (the view options popover button)."""
    view_controls = _find_widget(win, class_name="NautilusViewControls", site="find_sort_button")
    if view_controls is not None:
        for child in _all_widgets(view_controls):
            if isinstance(child, Gtk.MenuButton):
                return child

    # Structural fallback
    for w in _all_widgets(win):
        if is_split_button(w):
            for child in _all_widgets(w):
                if isinstance(child, Gtk.MenuButton):
                    return child
    return None


def _ancestor_split_button(widget: Gtk.Widget):
    current = widget
    while current is not None:
        if is_split_button(current):
            return current
        current = current.get_parent()
    return None


def find_split_button(win: Gtk.Window):
    """Finds the native Adw.SplitButton responsible for toggling view modes."""
    sort_btn = find_sort_button(win)
    if sort_btn is not None:
        sb = _ancestor_split_button(sort_btn)
        if sb is not None:
            return sb

    for widget in _all_widgets(win):
        if is_split_button(widget):
            action = widget.get_action_name() if hasattr(widget, "get_action_name") else None
            if action == _NATIVE_TOGGLE_ACTION:
                return widget
    return None


def _build_icon_size_row() -> Gtk.Widget:
    """Builds standard zoom-out/zoom-in button pair for the View Options popover."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    row.set_margin_start(6)
    row.set_margin_end(6)
    row.set_margin_top(6)
    row.set_margin_bottom(6)
    label = Gtk.Label(label="Icon Size", xalign=0.0, hexpand=True)
    row.append(label)

    for custom_id, icon_name, tooltip in (
        ("zoom-out", "zoom-out-symbolic", "Zoom Out"),
        ("zoom-in", "zoom-in-symbolic", "Zoom In"),
    ):
        button = Gtk.Button(icon_name=icon_name, tooltip_text=tooltip)
        button.set_action_name(f"view.{custom_id}")
        button.add_css_class("flat")
        row.append(button)
    return row


def _append_action_item(
    menu: Gio.Menu,
    label: str,
    action: str,
    target: GLib.Variant | None = None,
    *,
    hidden_when_disabled: bool = False,
    accel: str | None = None,
) -> None:
    item = Gio.MenuItem.new(label, action)
    if target is not None:
        item.set_attribute_value("target", target)
    if hidden_when_disabled:
        item.set_attribute_value("hidden-when", GLib.Variant.new_string("action-disabled"))
    if accel is not None:
        item.set_attribute_value("accel", GLib.Variant.new_string(accel))
    menu.append_item(item)


def _build_fallback_options_model() -> Gio.Menu:
    """Constructs a complete fallback View Options menu model when native model is inaccessible."""
    root = Gio.Menu()

    zoom = Gio.Menu()
    zoom_item = Gio.MenuItem.new(None, None)
    zoom_item.set_attribute_value("custom", GLib.Variant.new_string("icon-size-row"))
    zoom.append_item(zoom_item)
    root.append_section(None, zoom)

    sort = Gio.Menu()
    for label, token, reversed_order in (
        ("A-Z", "name", False),
        ("Z-A", "name", True),
        ("Last Modified", "date_modified", True),
        ("First Modified", "date_modified", False),
        ("Size", "size", True),
        ("Type", "type", False),
    ):
        _append_action_item(
            sort,
            label,
            "view.sort",
            GLib.Variant("(sb)", (token, reversed_order)),
            hidden_when_disabled=True,
        )
    root.append_section("Sort", sort)

    hidden = Gio.Menu()
    _append_action_item(
        hidden,
        "Show Hidden Files",
        "view.show-hidden-files",
        accel="<control>h",
    )
    root.append_section(None, hidden)

    visible_columns = Gio.Menu()
    _append_action_item(
        visible_columns,
        "Visible Columns…",
        "view.visible-columns",
        hidden_when_disabled=True,
    )
    root.append_section(None, visible_columns)

    captions = Gio.Menu()
    _append_action_item(
        captions,
        "Captions…",
        "view.visible-captions",
        hidden_when_disabled=True,
    )
    root.append_section(None, captions)

    return root


def inject_view_switcher(controller, win: Gtk.Window) -> bool:
    """Replaces NautilusViewControls content with the 3-segment switcher [Grid | List | Compact]."""
    ensure_resources_loaded()

    split_button = find_split_button(win)
    if split_button is None:
        log("inject_view_switcher: split_button not found yet")
        return False

    if getattr(split_button, "_compact_switcher_injected", False):
        return True

    view_controls = split_button.get_parent()
    if view_controls is None or not (is_bin(view_controls) or type(view_controls).__name__ == "NautilusViewControls"):
        log(f"inject_view_switcher: view_controls parent mismatch: {type(view_controls).__name__}")
        return False

    split_button.set_visible(False)
    split_button._compact_switcher_injected = True
    log("inject_view_switcher: hid native split_button, building 3-segment switcher...")

    # 1. 3-Segment Switcher
    segments = [
        ("grid", "view-grid-symbolic", "Grid View"),
        ("list", "view-list-symbolic", "List View"),
        ("compact", get_compact_icon(), "Compact List"),
    ]
    switcher = CompactListToggleButton(segments)
    switcher.set_name("compact-list-view-switcher")

    # 2. View Options Button
    options_btn = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="View Options")
    options_btn.set_name("compact-view-options-button")
    options_btn.add_css_class("flat")

    native_menu_model = split_button.get_menu_model() if hasattr(split_button, "get_menu_model") else None
    model_to_use = native_menu_model if native_menu_model is not None else _build_fallback_options_model()

    popover = Gtk.PopoverMenu.new_from_model(model_to_use)
    popover.add_child(_build_icon_size_row(), "icon-size-row")
    options_btn.set_popover(popover)

    # 3. Assemble container box
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.append(switcher)
    box.append(options_btn)

    if hasattr(view_controls, "set_child"):
        view_controls.set_child(None)
        box.append(split_button)
        view_controls.set_child(box)

    controller.register_switcher(win, switcher, split_button, options_btn)

    switcher.connect("changed", lambda _sw, name: controller.on_view_segment_activated(win, name))
    split_button.connect("notify::icon-name", lambda *_a: controller.sync_view_switcher(win))

    controller.sync_view_switcher(win)
    log(f"inject_view_switcher: successfully injected 3-segment switcher for window {win}")
    return True
