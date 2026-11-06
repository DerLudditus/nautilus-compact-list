import os
from dataclasses import dataclass
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

from gi.repository import Gtk, Gdk, Gio, GLib, GObject, Graphene, Pango
from .common import ensure_resources_loaded, get_style_metrics, log
from .native_selection import sync_selection_to_native, activate_uri_in_native_view
from .context_menu import CompactContextMenu
from .shortener import shorten_filename

QUERY_ATTRS = ",".join(
    [
        Gio.FILE_ATTRIBUTE_STANDARD_NAME,
        Gio.FILE_ATTRIBUTE_STANDARD_DISPLAY_NAME,
        Gio.FILE_ATTRIBUTE_STANDARD_TYPE,
        Gio.FILE_ATTRIBUTE_STANDARD_ICON,
        Gio.FILE_ATTRIBUTE_STANDARD_IS_HIDDEN,
        Gio.FILE_ATTRIBUTE_STANDARD_SIZE,
        Gio.FILE_ATTRIBUTE_TIME_MODIFIED,
    ]
)


def format_iec_size(num_bytes: int) -> str:
    """Formats bytes using GLib's localized IEC binary units (KiB, MiB, GiB / Gio, etc.)."""
    return GLib.format_size_full(num_bytes, GLib.FormatSizeFlags.IEC_UNITS)


@dataclass
class FileEntry:
    name: str
    display_name: str
    gfile: Gio.File
    uri: str
    is_dir: bool
    is_hidden: bool
    gicon: Gio.Icon
    size: int
    mtime: int


class CompactListView(Gtk.Box):
    """
    Classic Nautilus-style Compact List view with Variable-Width Columns (capped at max_column_width_chars
    with smart suffix-aware filename shortening), right-click context menu forwarding, and a
    bottom status bar showing folder/file counts, byte totals, and free space.
    """

    def __init__(self, window: Gtk.Window, prefs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        ensure_resources_loaded()
        self._window = window
        self.prefs = prefs
        self._native_files_view = None
        self._current_dir: Gio.File | None = None
        self._cancellable: Gio.Cancellable | None = None
        self._monitor: Gio.FileMonitor | None = None

        self.entries: list[FileEntry] = []
        self.row_widgets: list[Gtk.Box] = []
        self.selected_indices: set[int] = set()
        self._anchor_index: int | None = None
        self._rows_per_col: int = 20
        self._last_allocated_height: int = 0
        self._free_space_bytes: int | None = None

        self._icon_size = self.prefs.icon_size
        self._metrics = get_style_metrics()

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(True)

        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.add_css_class("compact-list-scroll")
        # In GTK4, EXTERNAL prevents the scrolled window from expanding to its child's size
        # and prevents showing vertical scrollbars, bounding height to the actual viewport.
        self._scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.EXTERNAL)
        self._scrolled.set_hexpand(True)
        self._scrolled.set_vexpand(True)

        self._columns_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._columns_box.add_css_class("compact-list-columns")
        self._columns_box.set_valign(Gtk.Align.FILL)
        self._scrolled.set_child(self._columns_box)

        self._update_zoom_metrics()

        # Monitor viewport page size changes directly on vadjustment (no overlay hack)
        vadj = self._scrolled.get_vadjustment()
        if vadj is not None:
            vadj.connect("notify::page-size", self._on_vadjustment_page_size_changed)

        # Banner at the top for special folders (Templates, scripts, etc.)
        self._banner = None
        self._banner_action_uri: str | None = None
        if Adw is not None and hasattr(Adw, "Banner"):
            self._banner = Adw.Banner.new("")
            self._banner.connect("button-clicked", self._on_banner_button_clicked)
            self.append(self._banner)

        # View stack: toggles between _scrolled (files present) and _empty_page (empty folder)
        self._view_stack = Gtk.Stack()
        self._view_stack.set_hexpand(True)
        self._view_stack.set_vexpand(True)
        self._view_stack.add_named(self._scrolled, "scrolled")

        if Adw is not None and hasattr(Adw, "StatusPage"):
            self._empty_page = Adw.StatusPage()
            self._empty_page.set_icon_name("folder-symbolic")
            self._empty_page.set_title(GLib.dgettext("nautilus", "Folder is Empty"))
        else:
            self._empty_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            self._empty_page.set_valign(Gtk.Align.CENTER)
            self._empty_page.set_halign(Gtk.Align.CENTER)
            lbl = Gtk.Label(label=GLib.dgettext("nautilus", "Folder is Empty"))
            lbl.add_css_class("title-1")
            self._empty_page.append(lbl)

        self._empty_page.set_hexpand(True)
        self._empty_page.set_vexpand(True)

        empty_bg_click = Gtk.GestureClick.new()
        empty_bg_click.set_button(0)
        empty_bg_click.connect("pressed", self._on_background_clicked)
        self._empty_page.add_controller(empty_bg_click)

        self._view_stack.add_named(self._empty_page, "empty")
        self.append(self._view_stack)

        self._status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._status_bar.add_css_class("compact-status-bar")
        self._status_label = Gtk.Label(label="")
        self._status_label.set_xalign(0.0)
        self._status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._status_bar.append(self._status_label)
        self.append(self._status_bar)

        self._context_menu = CompactContextMenu(self)

        scroll_ctrl = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll_ctrl.connect("scroll", self._on_mouse_wheel_scroll)
        self._scrolled.add_controller(scroll_ctrl)

        # Register 'view' action group so Nautilus window shortcuts (view.copy, view.cut, view.paste, view.select-all)
        # find and execute actions when CompactListView has focus
        view_actions = Gio.SimpleActionGroup()
        for act_name, cb in [
            ("copy", lambda *_: self.copy_to_clipboard(cut=False)),
            ("cut", lambda *_: self.copy_to_clipboard(cut=True)),
            ("paste", lambda *_: self.paste_from_clipboard()),
            ("select-all", lambda *_: self.select_all()),
        ]:
            act = Gio.SimpleAction.new(act_name, None)
            act.connect("activate", cb)
            view_actions.add_action(act)
        self.insert_action_group("view", view_actions)

        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        bg_click = Gtk.GestureClick.new()
        bg_click.set_button(0)
        bg_click.connect("pressed", self._on_background_clicked)
        self._scrolled.add_controller(bg_click)

    @property
    def native_files_view(self) -> Gtk.Widget | None:
        return self._native_files_view

    @property
    def current_dir(self) -> Gio.File | None:
        return self._current_dir

    def bind_native_view(self, native_files_view: Gtk.Widget):
        self._native_files_view = native_files_view

    def load_location(self, gfile: Gio.File):
        if gfile is None:
            return
        self._current_dir = gfile
        self._update_banner(gfile)

        if self._cancellable is not None:
            self._cancellable.cancel()
        self._cancellable = Gio.Cancellable()

        self._query_free_space(gfile)
        self._setup_directory_monitor(gfile)
        gfile.enumerate_children_async(
            QUERY_ATTRS,
            Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT,
            self._cancellable,
            self._on_enumerate_ready,
        )

    def reload(self):
        if self._current_dir is not None:
            self.load_location(self._current_dir)
        return GLib.SOURCE_REMOVE

    def _update_banner(self, gfile: Gio.File):
        if self._banner is None:
            return
        path = gfile.get_path()
        if not path:
            self._banner.set_revealed(False)
            return

        templates_dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_TEMPLATES)
        scripts_dir = os.path.expanduser("~/.local/share/nautilus/scripts")
        public_dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PUBLIC_SHARE)

        try:
            real_path = os.path.realpath(path)
        except Exception:
            real_path = path

        if templates_dir and real_path == os.path.realpath(templates_dir):
            self._banner.set_title(
                GLib.dgettext("nautilus", "Put files in this folder to use them as templates for new documents")
            )
            self._banner.set_button_label(GLib.dgettext("nautilus", "Learn More"))
            self._banner_action_uri = "help:gnome-help/files-templates"
            self._banner.set_revealed(True)
        elif scripts_dir and real_path == os.path.realpath(scripts_dir):
            self._banner.set_title(
                GLib.dgettext("nautilus", "Executable files in this folder will appear in the Scripts menu")
            )
            self._banner.set_button_label("")
            self._banner_action_uri = None
            self._banner.set_revealed(True)
        elif public_dir and real_path == os.path.realpath(public_dir):
            self._banner.set_title(
                GLib.dgettext("nautilus", "Turn on File Sharing to share the contents of this folder over the network")
            )
            self._banner.set_button_label("")
            self._banner_action_uri = None
            self._banner.set_revealed(True)
        else:
            self._banner.set_revealed(False)
            self._banner_action_uri = None

    def _on_banner_button_clicked(self, _banner):
        if getattr(self, "_banner_action_uri", None):
            try:
                launcher = Gtk.UriLauncher.new(self._banner_action_uri)
                launcher.launch(self._window, None, None)
            except Exception as err:
                log(f"Failed to launch banner URI: {err}")

    def _query_free_space(self, gfile: Gio.File):
        try:
            fs_info = gfile.query_filesystem_info(Gio.FILE_ATTRIBUTE_FILESYSTEM_FREE, None)
            if fs_info and fs_info.has_attribute(Gio.FILE_ATTRIBUTE_FILESYSTEM_FREE):
                self._free_space_bytes = fs_info.get_attribute_uint64(
                    Gio.FILE_ATTRIBUTE_FILESYSTEM_FREE
                )
            else:
                self._free_space_bytes = None
        except GLib.Error:
            self._free_space_bytes = None

    def _setup_directory_monitor(self, gfile: Gio.File):
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None
        try:
            self._monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", lambda *_args: self.reload())
        except GLib.Error:
            self._monitor = None

    def _on_enumerate_ready(self, gfile: Gio.File, result: Gio.AsyncResult):
        try:
            enumerator = gfile.enumerate_children_finish(result)
        except GLib.Error:
            return

        raw_entries: list[FileEntry] = []
        show_hidden = self.prefs.show_hidden

        while True:
            try:
                info = enumerator.next_file(self._cancellable)
            except GLib.Error:
                break
            if info is None:
                break

            name = info.get_name()
            is_hidden = info.get_is_hidden() or name.startswith(".")
            if is_hidden and not show_hidden:
                continue

            child_file = gfile.get_child(name)
            is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
            raw_entries.append(
                FileEntry(
                    name=name,
                    display_name=info.get_display_name() or name,
                    gfile=child_file,
                    uri=child_file.get_uri(),
                    is_dir=is_dir,
                    is_hidden=is_hidden,
                    gicon=info.get_icon() or Gio.ThemedIcon.new("text-x-generic"),
                    size=0 if is_dir else info.get_size(),
                    mtime=info.get_attribute_uint64(Gio.FILE_ATTRIBUTE_TIME_MODIFIED),
                )
            )

        self.entries = self._sort_entries(raw_entries)
        self.selected_indices.clear()
        self._anchor_index = None

        if hasattr(self, "_view_stack"):
            if not self.entries:
                self._view_stack.set_visible_child_name("empty")
            else:
                self._view_stack.set_visible_child_name("scrolled")

        if getattr(self, "_pending_select_name", None):
            for i, e in enumerate(self.entries):
                if e.name == self._pending_select_name:
                    self.selected_indices.add(i)
                    self._anchor_index = i
                    break
            self._pending_select_name = None

        self.rebuild_columns()
        self._update_status_bar()

    def _sort_entries(self, entries: list[FileEntry]) -> list[FileEntry]:
        order = self.prefs.sort_order
        reverse = self.prefs.sort_reversed
        dirs_first = self.prefs.sort_directories_first

        if order == "size":
            key_fn = lambda e: (e.size, e.display_name.casefold())
        elif order in ("mtime", "modification-date"):
            key_fn = lambda e: (e.mtime, e.display_name.casefold())
        else:
            key_fn = lambda e: e.display_name.casefold()

        sorted_list = sorted(entries, key=key_fn, reverse=reverse)
        if dirs_first:
            dirs = [e for e in sorted_list if e.is_dir]
            files = [e for e in sorted_list if not e.is_dir]
            return dirs + files
        return sorted_list

    def _update_zoom_metrics(self):
        self._metrics = get_style_metrics()
        self._icon_size = self.prefs.icon_size

    def _get_measured_row_height(self) -> int:
        if self.row_widgets:
            min_h, nat_h, _, _ = self.row_widgets[0].measure(Gtk.Orientation.VERTICAL, -1)
            if min_h > 0:
                return min_h if min_h >= self._icon_size else nat_h
        is_compact = (self._icon_size <= 16)
        pad_y, _ = self._metrics.get_cell_padding(is_compact)
        return max(self._icon_size + pad_y * 2, 18 + pad_y * 2)

    def _calculate_rows_per_col(self) -> int:
        page_size = 0
        vadj = self._scrolled.get_vadjustment()
        if vadj is not None:
            page_size = vadj.get_page_size()
        if page_size <= 0:
            page_size = self._scrolled.get_height()
        if page_size <= 0 and self._window is not None:
            win_h = self._window.get_height() if hasattr(self._window, "get_height") else 0
            if win_h > 150:
                page_size = win_h - 150
        if page_size <= 0:
            page_size = 500

        is_compact = (self._icon_size <= 16)
        border_spacing = self._metrics.get_border_spacing(is_compact)
        pad_top = self._metrics.padding_top
        pad_bottom = self._metrics.padding_bottom

        row_h = self._get_measured_row_height()
        row_pitch = max(1, row_h + border_spacing)
        usable_height = max(row_pitch, int(page_size) - pad_top - pad_bottom)
        return max(1, (usable_height + border_spacing) // row_pitch)

    def _on_vadjustment_page_size_changed(self, vadj, _pspec):
        new_rows = self._calculate_rows_per_col()
        if new_rows != self._rows_per_col:
            log(f"CompactListView: vadjustment page_size={vadj.get_page_size()}, rows_per_col {self._rows_per_col} -> {new_rows}")
            self._rows_per_col = new_rows
            self.rebuild_columns()

    def rebuild_columns(self):
        new_rows = self._calculate_rows_per_col()
        if new_rows > 0:
            self._rows_per_col = new_rows

        child = self._columns_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._columns_box.remove(child)
            child = nxt

        self.row_widgets.clear()
        if not self.entries:
            return

        max_chars = self.prefs.max_column_width_chars
        shortening_mode = self.prefs.shortening_mode

        is_compact = (self._icon_size <= 16)
        border_spacing = self._metrics.get_border_spacing(is_compact)

        r = max(1, self._rows_per_col)
        for col_start in range(0, len(self.entries), r):
            col_slice = self.entries[col_start : col_start + r]
            col_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=border_spacing)
            col_box.add_css_class("compact-list-column")
            col_box.set_valign(Gtk.Align.START)

            for offset, entry in enumerate(col_slice):
                idx = col_start + offset
                row = self._build_row_widget(idx, entry, max_chars, shortening_mode)
                self.row_widgets.append(row)
                col_box.append(row)

            self._columns_box.append(col_box)

        self._apply_selection_styles()

    def _build_row_widget(
        self, index: int, entry: FileEntry, max_chars: int, shortening_mode: str
    ) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.add_css_class("compact-list-row")
        is_compact = (self._icon_size <= 16)
        row.add_css_class("compact-cell" if is_compact else "normal-cell")
        row.set_hexpand(True)

        img = Gtk.Image.new_from_gicon(entry.gicon)
        img.set_pixel_size(self._icon_size)
        row.append(img)

        short_label = shorten_filename(
            entry.display_name, max_chars=max_chars, mode=shortening_mode
        )
        lbl = Gtk.Label(label=short_label)
        lbl.set_xalign(0.0)
        lbl.set_single_line_mode(True)
        lbl.set_ellipsize(Pango.EllipsizeMode.NONE)
        row.append(lbl)

        if short_label != entry.display_name:
            row.set_tooltip_text(entry.display_name)

        click = Gtk.GestureClick.new()
        click.set_button(0)
        click.connect("pressed", self._on_row_clicked, index, row)
        row.add_controller(click)

        return row

    def _on_row_clicked(
        self,
        gesture: Gtk.GestureClick,
        n_press: int,
        x: float,
        y: float,
        index: int,
        row: Gtk.Box,
    ):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.grab_focus()

        button = gesture.get_current_button()
        state = gesture.get_current_event_state()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if button == Gdk.BUTTON_PRIMARY:
            if shift and self._anchor_index is not None:
                lo, hi = sorted((self._anchor_index, index))
                if not ctrl:
                    self.selected_indices.clear()
                self.selected_indices.update(range(lo, hi + 1))
            elif ctrl:
                if index in self.selected_indices:
                    self.selected_indices.remove(index)
                else:
                    self.selected_indices.add(index)
                self._anchor_index = index
            else:
                self.selected_indices = {index}
                self._anchor_index = index

            self._apply_selection_styles()
            self.sync_to_native()
            self._update_status_bar()
            self._ensure_index_visible(index)

            if (n_press == 2 and not self.prefs.single_click_activate) or (
                n_press == 1 and self.prefs.single_click_activate and not (ctrl or shift)
            ):
                self._activate_index(index)

        elif button == Gdk.BUTTON_SECONDARY:
            if index not in self.selected_indices:
                self.selected_indices = {index}
                self._anchor_index = index
                self._apply_selection_styles()
                self.sync_to_native()
                self._update_status_bar()

            self._ensure_index_visible(index)

            src_pt = Graphene.Point()
            src_pt.x = x
            src_pt.y = y
            ok, pt = row.compute_point(self, src_pt)
            if ok:
                self._context_menu.popup_for_item(pt.x, pt.y)
            else:
                self._context_menu.popup_for_item(x, y)

    def _on_background_clicked(
        self, gesture: Gtk.GestureClick, _n_press: int, x: float, y: float
    ):
        self.grab_focus()
        button = gesture.get_current_button()
        self.selected_indices.clear()
        self._anchor_index = None
        self._apply_selection_styles()
        self.sync_to_native()
        self._update_status_bar()

        if button == Gdk.BUTTON_SECONDARY:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self._context_menu.popup_for_background(x, y)

    def _update_status_bar(self):
        if self.selected_indices:
            active_list = [
                self.entries[i] for i in self.selected_indices if 0 <= i < len(self.entries)
            ]
            sel_tmpl = GLib.dngettext(
                "nautilus", "%'d item selected", "%'d items selected", len(self.selected_indices)
            )
            sel_str = sel_tmpl.replace("%'d", "%d").replace("%'u", "%d").replace("%u", "%d") % len(self.selected_indices)
            prefix = f"{sel_str}: "
        else:
            active_list = self.entries
            prefix = ""

        num_folders = sum(1 for e in active_list if e.is_dir)
        files = [e for e in active_list if not e.is_dir]
        num_files = len(files)
        total_bytes = sum(e.size for e in files)

        parts: list[str] = []
        if self.selected_indices and num_folders > 0:
            folder_tmpl = GLib.dngettext(
                "nautilus", "%'d folder selected", "%'d folders selected", num_folders
            )
        else:
            folder_tmpl = GLib.dngettext("nautilus", "%'u folder", "%'u folders", num_folders)
        parts.append(
            folder_tmpl.replace("%'d", "%d").replace("%'u", "%d").replace("%u", "%d") % num_folders
        )

        file_tmpl = GLib.dngettext("nautilus", "%'u file", "%'u files", num_files)
        file_count_text = (
            file_tmpl.replace("%'d", "%d").replace("%'u", "%d").replace("%u", "%d") % num_files
        )
        if num_files > 0:
            iec_str = format_iec_size(total_bytes)
            byte_tmpl = GLib.dngettext("nautilus", "%s byte", "%s bytes", total_bytes)
            raw_bytes_str = byte_tmpl % f"{total_bytes:,}"
            parts.append(f"{file_count_text}: {iec_str} ({raw_bytes_str})")
        else:
            parts.append(file_count_text)

        if self._free_space_bytes is not None:
            free_iec = format_iec_size(self._free_space_bytes)
            free_tmpl = GLib.dgettext("nautilus", "%s Free")
            if free_tmpl and "%s" in free_tmpl:
                parts.append(free_tmpl % free_iec)
            else:
                parts.append(f"Free space: {free_iec}")

        self._status_label.set_text(prefix + " | ".join(parts))

    def select_all(self):
        self.selected_indices = set(range(len(self.entries)))
        if self.entries:
            self._anchor_index = 0
        self._apply_selection_styles()
        self.sync_to_native()
        self._update_status_bar()

    def activate_selected(self):
        if self._anchor_index is not None and 0 <= self._anchor_index < len(self.entries):
            self._activate_index(self._anchor_index)
        elif self.selected_indices:
            self._activate_index(next(iter(self.selected_indices)))

    def copy_to_clipboard(self, cut: bool = False):
        selected_uris = [
            self.entries[i].uri
            for i in sorted(self.selected_indices)
            if 0 <= i < len(self.entries)
        ]
        if not selected_uris:
            return
        display = Gdk.Display.get_default()
        if display is not None:
            clipboard = display.get_clipboard()
            file_list = Gdk.FileList.new_from_list([Gio.File.new_for_uri(u) for u in selected_uris])
            val = GObject.Value()
            val.init(Gdk.FileList)
            val.set_boxed(file_list)
            file_provider = Gdk.ContentProvider.new_for_value(val)

            nautilus_data = "\n".join(["cut" if cut else "copy", *selected_uris]).encode("utf-8")
            nautilus_provider = Gdk.ContentProvider.new_for_bytes(
                "x-special/gnome-copied-files", GLib.Bytes.new(nautilus_data)
            )
            provider = Gdk.ContentProvider.new_union([file_provider, nautilus_provider])
            clipboard.set_content(provider)

        self.sync_to_native()
        action = "view.cut" if cut else "view.copy"
        self._context_menu.trigger_native_view_action((action,))

    def paste_from_clipboard(self):
        if self._context_menu.trigger_native_view_action(("view.paste", "view.paste-into")):
            GLib.timeout_add(200, self.reload)
            return

        cur_dir = self._current_dir
        if cur_dir is None:
            return
        dest_uri = cur_dir.get_uri()

        display = Gdk.Display.get_default()
        if display is None:
            return
        clipboard = display.get_clipboard()

        def on_read_file_list(_cb, res):
            try:
                val = clipboard.read_value_finish(res)
                file_list = val.get_boxed()
                uris = [f.get_uri() for f in file_list.get_files()]
                if uris:
                    self._dispatch_copy_move_dbus(uris, dest_uri, move=False)
            except Exception as err:
                log(f"Paste read_value_finish failed: {err}")

        clipboard.read_value_async(
            Gdk.FileList.__gtype__, GLib.PRIORITY_DEFAULT, None, on_read_file_list
        )

    def _dispatch_copy_move_dbus(self, source_uris: list[str], dest_uri: str, move: bool = False):
        method = "MoveURIs" if move else "CopyURIs"
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call(
                "org.gnome.Nautilus",
                "/org/gnome/Nautilus/FileOperations2",
                "org.gnome.Nautilus.FileOperations2",
                method,
                GLib.Variant("(assa{sv})", (source_uris, dest_uri, {})),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            GLib.timeout_add(300, self.reload)
        except Exception as err:
            log(f"D-Bus {method} failed: {err}")
            dest_dir = Gio.File.new_for_uri(dest_uri)
            for s_uri in source_uris:
                src_file = Gio.File.new_for_uri(s_uri)
                name = src_file.get_basename()
                if name:
                    target_file = dest_dir.get_child(name)
                    try:
                        if move:
                            src_file.move(target_file, Gio.FileCopyFlags.OVERWRITE, None, None)
                        else:
                            src_file.copy(target_file, Gio.FileCopyFlags.OVERWRITE, None, None)
                    except GLib.Error as copy_err:
                        log(f"Fallback copy error: {copy_err}")
            self.reload()

    def trash_selected(self):
        self.sync_to_native()
        if self._context_menu.trigger_native_view_action(("view.move-to-trash",)):
            return

        # Fallback only if native action is completely unavailable
        indices = sorted(self.selected_indices)
        for idx in indices:
            if 0 <= idx < len(self.entries):
                try:
                    self.entries[idx].gfile.trash(None)
                except GLib.Error as err:
                    log(f"Trash failed for {self.entries[idx].uri}: {err}")
        self.selected_indices.clear()
        self._anchor_index = None
        self.reload()

    def delete_permanently_selected(self):
        self.sync_to_native()
        self._context_menu.trigger_native_view_action((
            "view.delete-permanently-shortcut",
            "view.delete-permanently-menu-item",
            "view.permanent-delete-permanently-menu-item",
        ))

    # Alias for backward compatibility
    trash_selected_fallback = trash_selected

    def zoom_in(self):
        sizes = (16, 32, 64)
        cur = self.prefs.icon_size
        if cur in sizes:
            idx = sizes.index(cur)
            if idx < len(sizes) - 1:
                self.prefs.icon_size = sizes[idx + 1]
                self._update_zoom_metrics()
                self.rebuild_columns()

    def zoom_out(self):
        sizes = (16, 32, 64)
        cur = self.prefs.icon_size
        if cur in sizes:
            idx = sizes.index(cur)
            if idx > 0:
                self.prefs.icon_size = sizes[idx - 1]
                self._update_zoom_metrics()
                self.rebuild_columns()

    def zoom_normal(self):
        self.prefs.icon_size = 16
        self._update_zoom_metrics()
        self.rebuild_columns()

    def _apply_selection_styles(self):
        for idx, row in enumerate(self.row_widgets):
            if idx in self.selected_indices:
                row.add_css_class("selected")
            else:
                row.remove_css_class("selected")

    def sync_to_native(self):
        if self._native_files_view is None:
            return
        uris = {self.entries[i].uri for i in self.selected_indices if 0 <= i < len(self.entries)}
        sync_selection_to_native(self._native_files_view, uris)

    def _activate_index(self, index: int):
        if 0 <= index < len(self.entries):
            entry = self.entries[index]
            activate_uri_in_native_view(
                self._window, self._native_files_view, entry.gfile, entry.is_dir
            )

    def _on_mouse_wheel_scroll(self, ctrl, dx: float, dy: float) -> bool:
        state = ctrl.get_current_event_state() if hasattr(ctrl, "get_current_event_state") else 0
        if state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK):
            delta = dy if abs(dy) > abs(dx) else dx
            if delta < 0:
                self.zoom_in()
            elif delta > 0:
                self.zoom_out()
            return True

        hadj = self._scrolled.get_hadjustment()
        if hadj is None:
            return False
        delta = dy if abs(dy) > abs(dx) else dx
        step = max(60.0, hadj.get_step_increment() or 60.0)
        hadj.set_value(hadj.get_value() + delta * step)
        return True

    def _on_key_pressed(
        self, _ctrl, keyval: int, _keycode: int, state: Gdk.ModifierType
    ) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.zoom_in()
            return True
        if ctrl and keyval in (Gdk.KEY_minus, Gdk.KEY_underscore, Gdk.KEY_KP_Subtract):
            self.zoom_out()
            return True
        if ctrl and keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.zoom_normal()
            return True

        if ctrl and keyval in (Gdk.KEY_a, Gdk.KEY_A):
            self.select_all()
            return True
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self.copy_to_clipboard(cut=False)
            return True
        if ctrl and keyval in (Gdk.KEY_x, Gdk.KEY_X):
            self.copy_to_clipboard(cut=True)
            return True
        if ctrl and keyval in (Gdk.KEY_v, Gdk.KEY_V):
            self.paste_from_clipboard()
            return True
        if keyval == Gdk.KEY_F2:
            self._context_menu.prompt_rename_selected()
            return True
        if keyval == Gdk.KEY_Delete:
            if shift:
                self.delete_permanently_selected()
            else:
                self.trash_selected()
            return True

        if not self.entries:
            return False

        n = len(self.entries)
        cur = self._anchor_index if self._anchor_index is not None else 0
        nxt = cur

        if keyval == Gdk.KEY_Down:
            nxt = min(n - 1, cur + 1)
        elif keyval == Gdk.KEY_Up:
            nxt = max(0, cur - 1)
        elif keyval == Gdk.KEY_Right:
            nxt = min(n - 1, cur + self._rows_per_col)
        elif keyval == Gdk.KEY_Left:
            nxt = max(0, cur - self._rows_per_col)
        elif keyval == Gdk.KEY_Home:
            nxt = 0
        elif keyval == Gdk.KEY_End:
            nxt = n - 1
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.activate_selected()
            return True
        elif keyval == Gdk.KEY_BackSpace:
            if self._current_dir is not None:
                parent = self._current_dir.get_parent()
                if parent is not None:
                    activate_uri_in_native_view(
                        self._window, self._native_files_view, parent, True
                    )
            return True
        else:
            return False

        if shift and self._anchor_index is not None:
            lo, hi = sorted((self._anchor_index, nxt))
            self.selected_indices = set(range(lo, hi + 1))
        else:
            self.selected_indices = {nxt}
            self._anchor_index = nxt

        self._apply_selection_styles()
        self.sync_to_native()
        self._update_status_bar()
        self._ensure_index_visible(nxt)
        return True

    def _get_item_pill_width(self, row: Gtk.Box) -> int:
        """Computes the exact pixel width of the item's selection pill and text."""
        img = row.get_first_child()
        lbl = img.get_next_sibling() if img is not None else None

        img_w = self._icon_size
        if img is not None:
            try:
                _, nat_img, _, _ = img.measure(Gtk.Orientation.HORIZONTAL, -1)
                if nat_img > 0:
                    img_w = nat_img
            except Exception:
                pass

        lbl_w = 0
        if lbl is not None:
            # 1. Direct Pango layout measurement (exact rendered pixel size)
            try:
                layout = lbl.get_layout() if hasattr(lbl, "get_layout") else None
                if layout is not None:
                    tw, _ = layout.get_pixel_size()
                    if tw > 0:
                        lbl_w = tw
            except Exception:
                pass

            # 2. GTK natural size measure fallback
            if lbl_w <= 0:
                try:
                    _, nat_lbl, _, _ = lbl.measure(Gtk.Orientation.HORIZONTAL, -1)
                    if nat_lbl > 0:
                        lbl_w = nat_lbl
                except Exception:
                    pass

            # 3. Text length heuristic fallback (average Cantarell character width ~9px)
            if lbl_w <= 0 and hasattr(lbl, "get_text"):
                lbl_w = int(len(lbl.get_text()) * 9)

        is_compact = (self._icon_size <= 16)
        _, pad_x = self._metrics.get_cell_padding(is_compact)
        spacing = row.get_spacing() if hasattr(row, "get_spacing") else 6

        # Pill width = left padding + icon + spacing + text + right padding
        return pad_x + img_w + spacing + lbl_w + pad_x

    def _ensure_index_visible(self, index: int):
        if not (0 <= index < len(self.row_widgets)):
            return
        row = self.row_widgets[index]
        success, bounds = row.compute_bounds(self._columns_box)
        if not success:
            col_box = row.get_parent()
            if col_box is None:
                return
            success, bounds = col_box.compute_bounds(self._columns_box)
            if not success:
                return

        hadj = self._scrolled.get_hadjustment()
        if hadj is None:
            return

        page_size = hadj.get_page_size()
        if page_size <= 0:
            return

        row_left = bounds.get_x()
        pill_w = self._get_item_pill_width(row)
        row_right = row_left + pill_w

        view_left = hadj.get_value()
        view_right = view_left + page_size
        margin = 24

        # Scroll right if the specific item extends beyond the right edge of the viewport
        if row_right + margin > view_right:
            if pill_w + margin * 2 <= page_size:
                target = row_right + margin - page_size
            else:
                target = max(0.0, row_left - margin)
            max_scroll = hadj.get_upper() - page_size
            if max_scroll > 0:
                target = min(target, max_scroll)
            hadj.set_value(max(0.0, target))

        # Scroll left if the item extends beyond the left edge of the viewport
        elif row_left - margin < view_left:
            target = max(0.0, row_left - margin)
            hadj.set_value(target)
