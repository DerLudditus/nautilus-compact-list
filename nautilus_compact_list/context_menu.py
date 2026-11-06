import os
import shutil
import gi

try:
    gi.require_version("Gtk", "4.0")
except (ValueError, AttributeError):
    pass

from gi.repository import Gtk, Gdk, Gio, GLib
from .common import log
from .i18n import _t


def show_file_properties(uris: list[str]):
    """Opens GNOME Files' native Properties dialog via D-Bus."""
    if not uris:
        return
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call(
            "org.freedesktop.FileManager1",
            "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1",
            "ShowItemProperties",
            GLib.Variant("(ass)", (uris, "")),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
    except Exception as err:
        log(f"ShowItemProperties D-Bus call failed: {err}")


def _find_action_label(menu_model: Gio.MenuModel, target_action: str) -> str | None:
    for i in range(menu_model.get_n_items()):
        act_val = menu_model.get_item_attribute_value(i, "action", GLib.VariantType.new("s"))
        if act_val and act_val.get_string() == target_action:
            lbl_val = menu_model.get_item_attribute_value(i, "label", GLib.VariantType.new("s"))
            if lbl_val:
                return lbl_val.get_string()
        sec = menu_model.get_item_link(i, Gio.MENU_LINK_SECTION)
        if sec:
            res = _find_action_label(sec, target_action)
            if res:
                return res
        sub = menu_model.get_item_link(i, Gio.MENU_LINK_SUBMENU)
        if sub:
            res = _find_action_label(sub, target_action)
            if res:
                return res
    return None


def get_native_menu_label(action_name: str, fallback_label: str) -> str:
    """Extracts the exact localized label used by Nautilus in other views."""
    try:
        builder = Gtk.Builder()
        builder.set_translation_domain("nautilus")
        builder.add_from_resource("/org/gnome/nautilus/ui/nautilus-files-view-context-menus.ui")
        for mid in ("background-menu", "selection-menu"):
            m = builder.get_object(mid)
            if m:
                lbl = _find_action_label(m, action_name)
                if lbl:
                    return lbl
    except Exception:
        pass
    return GLib.dgettext("nautilus", fallback_label)


def is_ubuntu_system() -> bool:
    """Detects whether the current operating system/session is Ubuntu Desktop."""
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").upper()
    if "UBUNTU" in desktop:
        return True
    try:
        if os.path.isfile("/etc/os-release"):
            with open("/etc/os-release", encoding="utf-8") as f:
                content = f.read().lower()
                if "id=ubuntu" in content or "id_like=ubuntu" in content or "ubuntu_codename=" in content:
                    return True
    except Exception:
        pass
    return False


def get_terminal_menu_label() -> str:
    """
    Returns the appropriate localized label for opening a terminal/console.
    - Fedora Workstation / upstream modern GNOME: 'Open in Consol_e' (ptyxis/kgx)
    - Ubuntu GNOME (tweaks GNOME to keep gnome-terminal): 'Open in Terminal'
    - Debian XFCE, KDE Plasma, MATE, Cinnamon, etc.: 'Open in Terminal'
    """
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").upper()
    is_ubuntu = is_ubuntu_system()
    is_gnome = ("GNOME" in desktop or is_ubuntu)

    if is_gnome and not is_ubuntu and (shutil.which("ptyxis") or shutil.which("kgx")):
        return get_native_menu_label("view.current-directory-console", "Open in Consol_e")

    for domain in ("gnome-terminal", "nautilus", "xfce4-terminal"):
        for msgid in ("Open in _Terminal", "Open in Terminal"):
            trans = GLib.dgettext(domain, msgid)
            if trans and trans not in ("Open in _Terminal", "Open in Terminal"):
                return trans.replace("_", "")

    lang = (os.environ.get("LANG") or os.environ.get("LANGUAGE") or "").split(".")[0].lower()
    lang_code = lang.split("_")[0]
    term_translations = {
        "fr": "Ouvrir dans un terminal",
        "de": "Im Terminal öffnen",
        "es": "Abrir en un terminal",
        "it": "Apri nel terminale",
        "pt": "Abrir no terminal",
        "ru": "Открыть в терминале",
        "pl": "Otwórz w terminalu",
        "nl": "In terminalvenster openen",
        "sv": "Öppna i terminal",
        "cs": "Otevřít v terminálu",
        "tr": "Uçbirimde Aç",
        "ja": "端末で開く",
        "zh": "在终端中打开",
    }
    return term_translations.get(lang_code, "Open in Terminal")


class CompactContextMenu:
    """
    Manages right-click context menus for items and empty background inside CompactListView,
    forwarding clipboard/file actions to the hidden native NautilusFilesView.
    """

    def __init__(self, compact_view):
        self._view = compact_view
        self._popover: Gtk.PopoverMenu | None = None
        self._last_click_x: float = 0.0
        self._last_click_y: float = 0.0
        self._action_group = Gio.SimpleActionGroup()
        self._view.insert_action_group("compact", self._action_group)
        self._register_actions()

    def _register_actions(self):
        actions = [
            ("open", self._on_open),
            ("open-new-tab", self._on_open_new_tab),
            ("cut", self._on_cut),
            ("copy", self._on_copy),
            ("paste", self._on_paste),
            ("rename", self._on_rename),
            ("trash", self._on_trash),
            ("delete-permanently", self._on_delete_permanently),
            ("properties", self._on_properties),
            ("new-folder", self._on_new_folder),
            ("select-all", self._on_select_all),
            ("max-col-width", self._on_max_col_width),
            ("open-terminal", self._on_open_terminal),
            ("folder-properties", self._on_folder_properties),
        ]
        for name, callback in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self._action_group.add_action(action)

        template_action = Gio.SimpleAction.new("new-from-template", GLib.VariantType.new("s"))
        template_action.connect("activate", self._on_new_from_template)
        self._action_group.add_action(template_action)

    def popup_for_item(self, x: float, y: float):
        self._last_click_x = x
        self._last_click_y = y
        menu = Gio.Menu()

        open_sec = Gio.Menu()
        open_label = get_native_menu_label("view.open-with-default-application", "Open")
        open_sec.append(open_label, "compact.open")
        if len(self._view.selected_indices) == 1:
            idx = next(iter(self._view.selected_indices))
            if self._view.entries[idx].is_dir:
                tab_label = get_native_menu_label("view.open-item-new-tab", "Open in New _Tab")
                open_sec.append(tab_label, "compact.open-new-tab")
        menu.append_section(None, open_sec)

        clip_sec = Gio.Menu()
        clip_sec.append(get_native_menu_label("view.cut", "Cu_t"), "compact.cut")
        clip_sec.append(get_native_menu_label("view.copy", "_Copy"), "compact.copy")
        menu.append_section(None, clip_sec)

        edit_sec = Gio.Menu()
        if len(self._view.selected_indices) == 1:
            edit_sec.append(get_native_menu_label("view.rename", "Rena_me…"), "compact.rename")
        edit_sec.append(get_native_menu_label("view.move-to-trash", "Mo_ve to Trash"), "compact.trash")
        edit_sec.append(get_native_menu_label("view.delete-permanently-menu-item", "_Delete Permanently…"), "compact.delete-permanently")
        menu.append_section(None, edit_sec)

        prop_sec = Gio.Menu()
        prop_sec.append(get_native_menu_label("view.properties", "P_roperties"), "compact.properties")
        menu.append_section(None, prop_sec)

        self._show_popover_menu(menu, x, y)

    def popup_for_background(self, x: float, y: float):
        self._last_click_x = x
        self._last_click_y = y
        menu = Gio.Menu()

        create_sec = Gio.Menu()
        create_sec.append(get_native_menu_label("view.new-folder", "New _Folder…"), "compact.new-folder")

        templates_menu = self._build_templates_menu()
        if templates_menu is not None:
            new_doc_label = GLib.dgettext("nautilus", "New _Document")
            if new_doc_label == "New _Document":
                new_doc_label = "New Document"
            create_sec.append_submenu(new_doc_label, templates_menu)

        menu.append_section(None, create_sec)

        clip_sec = Gio.Menu()
        clip_sec.append(get_native_menu_label("view.paste", "_Paste"), "compact.paste")
        clip_sec.append(get_native_menu_label("view.select-all", "Select _All"), "compact.select-all")
        menu.append_section(None, clip_sec)

        cfg_sec = Gio.Menu()
        cfg_sec.append(_t("Set Max Column Width…"), "compact.max-col-width")
        menu.append_section(None, cfg_sec)

        term_sec = Gio.Menu()
        term_label = get_terminal_menu_label()
        term_sec.append(term_label, "compact.open-terminal")

        prop_label = get_native_menu_label("view.current-directory-properties", "P_roperties")
        term_sec.append(prop_label, "compact.folder-properties")
        menu.append_section(None, term_sec)

        self._show_popover_menu(menu, x, y)

    def _build_templates_menu(self) -> Gio.Menu | None:
        templates_dir_path = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_TEMPLATES)
        if not templates_dir_path or not os.path.isdir(templates_dir_path):
            return None

        def _scan_folder(folder_path: str) -> Gio.Menu | None:
            try:
                entries = sorted(os.listdir(folder_path))
            except OSError:
                return None

            sub_menu = Gio.Menu()
            count = 0
            for name in entries:
                if name.startswith(".") or name.endswith("~"):
                    continue
                full_path = os.path.join(folder_path, name)
                if os.path.isdir(full_path):
                    nested = _scan_folder(full_path)
                    if nested is not None:
                        sub_menu.append_submenu(name, nested)
                        count += 1
                elif os.path.isfile(full_path):
                    item = Gio.MenuItem.new(name, "compact.new-from-template")
                    item.set_action_and_target_value(
                        "compact.new-from-template", GLib.Variant.new_string(full_path)
                    )
                    sub_menu.append_item(item)
                    count += 1

            return sub_menu if count > 0 else None

        return _scan_folder(templates_dir_path)

    def _on_new_from_template(self, _action, param):
        if param is None:
            return
        template_path = param.get_string()
        if not os.path.isfile(template_path):
            return
        cur_dir = self._view.current_dir
        if cur_dir is None:
            return

        base_name = os.path.basename(template_path)
        stem, ext = os.path.splitext(base_name)
        target_name = base_name

        count = 1
        while True:
            target_child = cur_dir.get_child(target_name)
            if not target_child.query_exists(None):
                break
            count += 1
            target_name = f"{stem} ({count}){ext}"

        template_file = Gio.File.new_for_path(template_path)
        try:
            template_file.copy(target_child, Gio.FileCopyFlags.NONE, None, None)
            self._view._pending_select_name = target_name
            self._view.reload()
        except GLib.Error as err:
            log(f"Failed to copy template: {err}")

    def _show_popover_menu(self, menu_model: Gio.Menu, x: float, y: float):
        if self._popover is not None:
            self._popover.unparent()

        self._popover = Gtk.PopoverMenu.new_from_model(menu_model)
        self._popover.set_parent(self._view)
        self._popover.set_has_arrow(False)

        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def trigger_native_view_action(self, action_names: tuple[str, ...]) -> bool:
        files_view = self._view.native_files_view
        if files_view is None:
            return False
        self._view.sync_to_native()
        for name in action_names:
            if hasattr(files_view, "activate_action") and files_view.activate_action(name, None):
                return True
        return False

    def _on_open(self, *_args):
        self._view.activate_selected()

    def _on_open_new_tab(self, *_args):
        self.trigger_native_view_action(("view.open-item-new-tab",))

    def _on_cut(self, *_args):
        self._view.copy_to_clipboard(cut=True)

    def _on_copy(self, *_args):
        self._view.copy_to_clipboard(cut=False)

    def _on_paste(self, *_args):
        self._view.paste_from_clipboard()

    def _on_rename(self, *_args):
        self.prompt_rename_selected()

    def _on_trash(self, *_args):
        self._view.trash_selected()

    def _on_delete_permanently(self, *_args):
        self._view.delete_permanently_selected()

    def _on_properties(self, *_args):
        self.trigger_native_view_action(("view.properties",))
        selected_uris = [
            self._view.entries[i].uri
            for i in sorted(self._view.selected_indices)
            if 0 <= i < len(self._view.entries)
        ]
        if selected_uris:
            show_file_properties(selected_uris)

    def _on_new_folder(self, *_args):
        self.prompt_new_folder()

    def _on_select_all(self, *_args):
        self._view.select_all()

    def _on_max_col_width(self, *_args):
        self.prompt_max_column_width()

    def _on_open_terminal(self, *_args):
        cur_dir = self._view.current_dir
        if cur_dir is None or cur_dir.get_path() is None:
            return
        workdir = cur_dir.get_path()

        is_ubuntu = is_ubuntu_system()

        # Ubuntu GNOME priority: Ubuntu tweaks GNOME to keep gnome-terminal as the primary terminal
        if is_ubuntu and shutil.which("gnome-terminal"):
            if self._launch_terminal_binary("gnome-terminal", workdir):
                return

        # Priority 1: GNOME default terminal / console (Nautilus belongs to GNOME)
        gnome_term = self._get_gsettings_terminal("org.gnome.desktop.default-applications.terminal")
        if gnome_term and gnome_term != "x-terminal-emulator":
            if self._launch_terminal_binary(gnome_term, workdir):
                return

        # 1b. Probing native GNOME terminal binaries (ptyxis on Fedora/modern GNOME, kgx, gnome-terminal)
        gnome_bins = ("gnome-terminal", "ptyxis", "kgx") if is_ubuntu else ("ptyxis", "kgx", "gnome-terminal")
        for term_name in gnome_bins:
            if shutil.which(term_name):
                if self._launch_terminal_binary(term_name, workdir):
                    return

        # Priority 2: Equivalent for current desktop environment
        desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").upper()

        # 2a. KDE Plasma
        if "KDE" in desktop or os.environ.get("KDE_FULL_SESSION"):
            kde_term = self._get_kde_terminal()
            if kde_term and self._launch_terminal_binary(kde_term, workdir):
                return

        # 2b. XFCE (exo-preferred-applications)
        if "XFCE" in desktop or shutil.which("exo-open"):
            if shutil.which("exo-open"):
                if self._spawn_cmd(
                    ["exo-open", "--working-directory", workdir, "--launch", "TerminalEmulator"],
                    workdir,
                ):
                    return

        # 2c. Cinnamon
        if "CINNAMON" in desktop:
            cin_term = self._get_gsettings_terminal("org.cinnamon.desktop.default-applications.terminal")
            if cin_term and self._launch_terminal_binary(cin_term, workdir):
                return

        # 2d. MATE
        if "MATE" in desktop:
            mate_term = self._get_gsettings_terminal("org.mate.applications-terminal")
            if mate_term and self._launch_terminal_binary(mate_term, workdir):
                return

        # Priority 3: xdg-terminal-exec (Freedesktop standard)
        if shutil.which("xdg-terminal-exec"):
            if self._spawn_cmd(["xdg-terminal-exec", "--dir", workdir], workdir):
                return

        # Priority 4: x-terminal-emulator (Debian / system default)
        if shutil.which("x-terminal-emulator"):
            if self._spawn_cmd(["x-terminal-emulator"], workdir):
                return

        # NO OTHER FALLBACK!

    def _get_kde_terminal(self) -> str | None:
        for kread in ("kreadconfig6", "kreadconfig5"):
            if shutil.which(kread):
                try:
                    launcher = Gio.SubprocessLauncher.new(
                        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
                    )
                    proc = launcher.spawnv([
                        kread,
                        "--file",
                        "kdeglobals",
                        "--group",
                        "General",
                        "--key",
                        "TerminalApplication",
                    ])
                    success, stdout, _ = proc.communicate_utf8(None, None)
                    if success and stdout and stdout.strip():
                        return stdout.strip()
                except Exception:
                    pass
        kdeglobals = os.path.expanduser("~/.config/kdeglobals")
        if os.path.isfile(kdeglobals):
            try:
                import configparser

                cp = configparser.RawConfigParser()
                cp.read(kdeglobals, encoding="utf-8")
                if cp.has_option("General", "TerminalApplication"):
                    term = cp.get("General", "TerminalApplication").strip()
                    if term:
                        return term
            except Exception:
                pass
        if shutil.which("konsole"):
            return "konsole"
        return None

    def _get_gsettings_terminal(self, schema_id: str) -> str | None:
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if source and source.lookup(schema_id, True):
                settings = Gio.Settings.new(schema_id)
                term = settings.get_string("exec")
                return term.strip() if term and term.strip() else None
        except Exception:
            pass
        return None

    def _launch_terminal_binary(self, term: str, workdir: str) -> bool:
        if not shutil.which(term):
            return False
        base = os.path.basename(term).lower()
        if base in ("ptyxis", "kgx", "gnome-terminal", "alacritty"):
            cmd = [term, "--working-directory", workdir]
        elif base in ("xfce4-terminal", "mate-terminal"):
            cmd = [term, f"--working-directory={workdir}"]
        elif base == "konsole":
            cmd = [term, "--workdir", workdir]
        elif base == "kitty":
            cmd = [term, "--directory", workdir]
        else:
            cmd = [term]
        return self._spawn_cmd(cmd, workdir)

    def _spawn_cmd(self, cmd: list[str], workdir: str) -> bool:
        try:
            launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.NONE)
            launcher.set_cwd(workdir)
            launcher.spawnv(cmd)
            return True
        except Exception as err:
            log(f"Failed to spawn {cmd}: {err}")
            return False

    def _on_folder_properties(self, *_args):
        self.trigger_native_view_action(("view.current-location-properties", "view.properties"))
        cur_dir = self._view.current_dir
        if cur_dir is not None:
            show_file_properties([cur_dir.get_uri()])

    def prompt_rename_selected(self):
        if len(self._view.selected_indices) != 1:
            return
        idx = next(iter(self._view.selected_indices))
        if not (0 <= idx < len(self._view.entries)):
            return

        entry = self._view.entries[idx]
        row_widget = self._view.row_widgets[idx]

        pop = Gtk.Popover()
        pop.set_parent(row_widget)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        text_entry = Gtk.Entry()
        text_entry.set_text(entry.display_name)
        text_entry.set_width_chars(24)

        btn = Gtk.Button(label="Rename")
        btn.add_css_class("suggested-action")

        def do_rename(*_a):
            new_name = text_entry.get_text().strip()
            pop.popdown()
            pop.unparent()
            if new_name and new_name != entry.display_name:
                try:
                    entry.gfile.set_display_name(new_name, None)
                    self._view.reload()
                except GLib.Error:
                    pass

        text_entry.connect("activate", do_rename)
        btn.connect("clicked", do_rename)

        box.append(text_entry)
        box.append(btn)
        pop.set_child(box)
        pop.popup()

        if (
            not entry.is_dir
            and "." in entry.display_name
            and not entry.display_name.startswith(".")
        ):
            stem_len = entry.display_name.rfind(".")
            text_entry.select_region(0, stem_len)
        else:
            text_entry.select_region(0, -1)
        text_entry.grab_focus()

    def prompt_new_folder(self):
        cur_dir = self._view.current_dir
        if cur_dir is None:
            return

        pop = Gtk.Popover()
        pop.set_parent(self._view)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        text_entry = Gtk.Entry()
        default_folder = GLib.dgettext("nautilus", "Untitled Folder")
        text_entry.set_text(default_folder if default_folder else "Untitled Folder")
        text_entry.set_width_chars(24)

        create_label = GLib.dgettext("gtk40", "_Create").replace("_", "")
        if not create_label or create_label == "Create":
            create_label = GLib.dgettext("nautilus", "Create")
        btn = Gtk.Button(label=create_label if create_label else "Create")
        btn.add_css_class("suggested-action")

        def do_create(*_a):
            folder_name = text_entry.get_text().strip()
            pop.popdown()
            pop.unparent()
            if folder_name:
                try:
                    target = cur_dir.get_child_for_display_name(folder_name)
                    target.make_directory(None)
                    self._view.reload()
                except GLib.Error:
                    pass

        text_entry.connect("activate", do_create)
        btn.connect("clicked", do_create)

        box.append(text_entry)
        box.append(btn)
        pop.set_child(box)

        rect = Gdk.Rectangle()
        rect.x = int(self._last_click_x) if self._last_click_x > 0 else max(20, self._view.get_width() // 2)
        rect.y = int(self._last_click_y) if self._last_click_y > 0 else max(20, self._view.get_height() // 2)
        rect.width = 1
        rect.height = 1
        pop.set_pointing_to(rect)
        pop.set_position(Gtk.PositionType.BOTTOM)

        pop.popup()
        text_entry.select_region(0, -1)
        text_entry.grab_focus()

    def prompt_max_column_width(self):
        pop = Gtk.Popover()
        pop.set_parent(self._view)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        lbl = Gtk.Label(label=_t("Max chars:"))
        spin = Gtk.SpinButton.new_with_range(15, 200, 1)
        spin.set_value(self._view.prefs.max_column_width_chars)

        btn = Gtk.Button(label=_t("Apply"))
        btn.add_css_class("suggested-action")

        def do_apply(*_a):
            new_max = int(spin.get_value())
            pop.popdown()
            pop.unparent()
            self._view.prefs.max_column_width_chars = new_max
            self._view.rebuild_columns()

        spin.connect("activate", do_apply)
        btn.connect("clicked", do_apply)

        box.append(lbl)
        box.append(spin)
        box.append(btn)
        pop.set_child(box)

        rect = Gdk.Rectangle()
        rect.x = int(self._last_click_x) if self._last_click_x > 0 else max(20, self._view.get_width() // 2)
        rect.y = int(self._last_click_y) if self._last_click_y > 0 else max(20, self._view.get_height() // 2)
        rect.width = 1
        rect.height = 1
        pop.set_pointing_to(rect)
        pop.set_position(Gtk.PositionType.BOTTOM)

        pop.popup()
        spin.grab_focus()
