import datetime
import os
import sys
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
from .style_metrics import load_style_metrics, StyleMetrics

_LOG_FILE = "/tmp/nautilus-compact-list.log"
_metrics: StyleMetrics | None = None


def get_style_metrics() -> StyleMetrics:
    global _metrics
    if _metrics is None:
        _metrics = load_style_metrics()
    return _metrics


def log(msg: str) -> None:
    """Logs timestamped debug message only when NAUTILUS_COMPACT_LIST_DEBUG == '1'."""
    if os.environ.get("NAUTILUS_COMPACT_LIST_DEBUG") != "1":
        return
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    pid = os.getpid()
    line = f"[{timestamp}] [PID {pid}] {msg}"
    print(f"NautilusCompactList: {msg}", file=sys.stderr, flush=True)
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

COMPACT_CSS = """
.compact-list-scroll {
    background-color: @view_bg_color;
    color: @view_fg_color;
}
.compact-list-row:hover {
    background-color: alpha(@view_fg_color, 0.07);
}
.compact-list-row.selected {
    background-color: @accent_bg_color;
    color: @accent_fg_color;
}
.compact-status-bar {
    background-color: @view_bg_color;
    box-shadow: inset 0 100px 0 0 alpha(currentColor, 0.10);
    border-top: 1px solid alpha(currentColor, 0.12);
    color: @view_fg_color;
    padding: 3px 0;
}
.compact-status-bar label {
    margin: 2px 12px;
    padding: 0;
}
.mc-toggle-group {
    background-color: alpha(@window_fg_color, 0.07);
    border-radius: 9px;
    padding: 2px;
}
.mc-toggle-btn {
    border-radius: 7px;
    padding: 0 0;
    min-height: 0;
    transition: background-color 200ms ease;
}
.mc-toggle-btn:hover {
    background-color: alpha(@window_fg_color, 0.07);
}
.mc-toggle-btn:checked {
    background-color: @view_bg_color;
}
.mc-toggle-sep {
    opacity: 1;
    transition: opacity 200ms ease;
}
.mc-toggle-sep.mc-toggle-sep-hidden {
    opacity: 0;
}
"""

_css_loaded = False


def ensure_resources_loaded():
    global _css_loaded
    if _css_loaded:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return

    provider = Gtk.CssProvider()
    full_css = COMPACT_CSS + "\n" + get_style_metrics().generate_css()
    provider.load_from_string(full_css)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    icons_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
    if os.path.isdir(icons_dir):
        icon_theme = Gtk.IconTheme.get_for_display(display)
        icon_theme.add_search_path(icons_dir)

    _css_loaded = True


def get_compact_icon():
    """Returns a Gio.Icon for the bundled view-compact-symbolic.svg fallback."""
    svg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "view-compact-symbolic.svg")
    if os.path.isfile(svg_path):
        f = Gio.File.new_for_path(svg_path)
        return Gio.FileIcon.new(f)
    return "view-compact-symbolic"


def is_split_button(widget) -> bool:
    if widget is None:
        return False
    if Adw is not None and hasattr(Adw, "SplitButton") and isinstance(widget, Adw.SplitButton):
        return True
    return type(widget).__name__ in ("AdwSplitButton", "SplitButton")


def is_bin(widget) -> bool:
    if widget is None:
        return False
    if Adw is not None and hasattr(Adw, "Bin") and isinstance(widget, Adw.Bin):
        return True
    return type(widget).__name__ in ("AdwBin", "Bin", "NautilusViewControls")


def get_type_name(widget) -> str:
    if widget is None:
        return ""
    return GObject.type_name(widget.__gtype__)


def iter_children(widget: Gtk.Widget):
    if widget is None:
        return
    child = widget.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        yield child
        child = nxt


def _all_widgets(widget: Gtk.Widget):
    """Depth-first traversal of widget and all descendants."""
    if widget is None:
        return
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _all_widgets(child)
        child = child.get_next_sibling()


def walk_widgets(root: Gtk.Widget):
    return _all_widgets(root)


def find_first_by_type_name(root: Gtk.Widget, type_names: tuple[str, ...]):
    for w in _all_widgets(root):
        if get_type_name(w) in type_names or type(w).__name__ in type_names:
            return w
    return None


def find_all_by_type_name(root: Gtk.Widget, type_names: tuple[str, ...]) -> list[Gtk.Widget]:
    return [w for w in _all_widgets(root) if get_type_name(w) in type_names or type(w).__name__ in type_names]


def _find_widget(root: Gtk.Widget, *, buildable_id=None, class_name=None, css_class=None, site=""):
    """Find a widget by layered fallback: buildable_id -> class_name -> css_class."""
    tier1 = tier2 = tier3 = None
    for w in _all_widgets(root):
        if tier1 is None and buildable_id is not None:
            bid = w.get_buildable_id() if hasattr(w, "get_buildable_id") else None
            if bid and bid == buildable_id and not bid.startswith("___object_"):
                tier1 = w
        if tier2 is None and class_name is not None:
            if type(w).__name__ == class_name:
                tier2 = w
        if tier3 is None and css_class is not None:
            if hasattr(w, "has_css_class") and w.has_css_class(css_class):
                tier3 = w
        if tier1 is not None:
            break
    return tier1 or tier2 or tier3


def _is_nautilus_window(win: Gtk.Window) -> bool:
    """Identify a Nautilus application window by layered fallback."""
    if win is None:
        return False
    bid = win.get_buildable_id() if hasattr(win, "get_buildable_id") else None
    if bid and bid == "NautilusWindow":
        return True
    if type(win).__name__ == "NautilusWindow":
        return True
    if hasattr(win, "has_css_class") and win.has_css_class("nautilus-window"):
        return True
    if Adw is not None and hasattr(Adw, "OverlaySplitView"):
        if any(isinstance(w, Adw.OverlaySplitView) for w in _all_widgets(win)):
            return True
    for w in _all_widgets(win):
        if type(w).__name__ in ("NautilusWindowSlot", "NautilusViewControls"):
            return True
    return False


def _find_tab_view(win: Gtk.Window):
    """Finds the Adw.TabView housing tabs in NautilusWindow."""
    if Adw is not None and hasattr(Adw, "TabView"):
        return next((w for w in _all_widgets(win) if isinstance(w, Adw.TabView)), None)
    return next((w for w in _all_widgets(win) if type(w).__name__ == "TabView"), None)


def _find_slot_stack(slot: Gtk.Widget) -> Gtk.Stack | None:
    """The slot's own top-level GtkStack (nautilus-window-slot.c: self->stack)."""
    return next((w for w in _all_widgets(slot) if isinstance(w, Gtk.Stack)), None)


def watch_slots(win: Gtk.Window, on_slot) -> None:
    """Invoke on_slot(win, slot) for every current and future tab slot."""
    tab_view = _find_tab_view(win)
    if tab_view is None:
        for slot in find_all_by_type_name(win, ("NautilusWindowSlot",)):
            on_slot(win, slot)
        return

    n_pages = tab_view.get_n_pages() if hasattr(tab_view, "get_n_pages") else 0
    for i in range(n_pages):
        page = tab_view.get_nth_page(i)
        slot = page.get_child() if page is not None and hasattr(page, "get_child") else None
        if slot is not None:
            on_slot(win, slot)

    if hasattr(tab_view, "connect"):
        tab_view.connect(
            "page-attached",
            lambda _tv, page, _pos, win=win, on_slot=on_slot: on_slot(win, page.get_child() if hasattr(page, "get_child") else page),
        )


def schedule_slot_init(
    slot: Gtk.Widget,
    marker_attr: str,
    do_inject,
    *,
    retry_ms: int = 20,
    max_attempts: int = 100,
) -> None:
    """Defer do_inject(slot) until slot's location resolves."""
    if getattr(slot, marker_attr, None) is not None:
        return
    attempts = [0]

    def _try() -> bool:
        if getattr(slot, marker_attr, None) is not None:
            return GLib.SOURCE_REMOVE
        attempts[0] += 1
        loc = None
        if hasattr(slot, "find_property") and slot.find_property("location") is not None:
            loc = slot.get_property("location")
        if loc is None and attempts[0] <= max_attempts:
            return GLib.SOURCE_CONTINUE
        setattr(slot, marker_attr, True)
        GLib.idle_add(do_inject, slot, priority=GLib.PRIORITY_LOW)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(retry_ms, _try)
