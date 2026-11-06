import gi

try:
    gi.require_version("Gtk", "4.0")
except (ValueError, AttributeError):
    pass

try:
    gi.require_version("Nautilus", "4.0")
except (ValueError, AttributeError):
    pass

from gi.repository import Gio, GLib, Gtk, Nautilus
from .common import walk_widgets, get_type_name, log


def get_native_selection_model(files_view: Gtk.Widget):
    """Locates the selection model (NautilusViewModel) inside NautilusFilesView."""
    if files_view is None:
        return None
    for w in walk_widgets(files_view):
        if isinstance(w, (Gtk.ListView, Gtk.GridView)):
            model = w.get_model()
            if model is not None and hasattr(model, "get_n_items"):
                return model
        t_name = get_type_name(w)
        if t_name in ("GtkListView", "GtkGridView", "GtkColumnView"):
            if hasattr(w, "get_model"):
                model = w.get_model()
                if model is not None and hasattr(model, "get_n_items"):
                    return model
    return None


# Backward-compatible alias
get_native_multi_selection = get_native_selection_model


def _extract_item_uri(obj) -> str | None:
    """Extracts the URI from a NautilusViewItem or TreeListRow in the native model."""
    if obj is None:
        return None
    if isinstance(obj, Gtk.TreeListRow):
        obj = obj.get_item()
        if obj is None:
            return None
    for prop in ("file", "uri"):
        if hasattr(obj, "find_property") and obj.find_property(prop) is not None:
            val = obj.get_property(prop)
            if isinstance(val, str):
                return val
            if isinstance(val, Nautilus.FileInfo):
                return val.get_uri()
            if val is not None and hasattr(val, "get_uri"):
                return val.get_uri()
    return None


def sync_selection_to_native(files_view: Gtk.Widget, selected_uris: set[str]):
    """Mirrors the custom view's selection into the hidden native NautilusFilesView."""
    model = get_native_selection_model(files_view)
    if model is None or not hasattr(model, "get_n_items"):
        return

    n_items = model.get_n_items()
    if n_items == 0:
        return

    selected_bitset = Gtk.Bitset.new_empty()
    if selected_uris:
        norm_targets = set()
        for u in selected_uris:
            try:
                norm_targets.add(Gio.File.new_for_uri(u).get_uri())
            except Exception:
                norm_targets.add(u)

        for i in range(n_items):
            item = model.get_item(i)
            if item is None:
                continue
            uri = _extract_item_uri(item)
            if uri is not None:
                try:
                    norm_u = Gio.File.new_for_uri(uri).get_uri()
                except Exception:
                    norm_u = uri
                if norm_u in norm_targets:
                    selected_bitset.add(i)

    if hasattr(model, "set_selection"):
        model.set_selection(selected_bitset, Gtk.Bitset.new_range(0, n_items))
    elif hasattr(model, "select_item"):
        if hasattr(model, "unselect_all"):
            model.unselect_all()
        for i in range(n_items):
            if selected_bitset.contains(i):
                model.select_item(i, False)


def activate_uri_in_native_view(window: Gtk.Window, files_view: Gtk.Widget, gfile, is_dir: bool):
    """Navigates into directories inside the active slot or opens files natively."""
    uri = gfile.get_uri()
    sync_selection_to_native(files_view, {uri})

    if is_dir:
        for target, action_name in (
            (files_view, "slot.open-location"),
            (window, "slot.open-location"),
            (window, "win.open-location"),
        ):
            if target is not None and hasattr(target, "activate_action"):
                res = target.activate_action(action_name, GLib.Variant.new_string(uri))
                if res:
                    return
        return

    # For regular files: open with default desktop application
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
        return
    except GLib.Error as err:
        log(f"launch_default_for_uri failed for {uri}: {err}")

    if window is not None:
        try:
            launcher = Gtk.UriLauncher.new(uri)
            launcher.launch(window, None, None)
        except Exception as err:
            log(f"UriLauncher failed for {uri}: {err}")
