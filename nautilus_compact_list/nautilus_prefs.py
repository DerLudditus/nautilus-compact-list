import json
import os
from gi.repository import Gio, GLib

EXT_SCHEMA_ID = "io.github.nautilus-compact-list"


class NautilusPrefs:
    def __init__(self, on_changed_cb=None):
        self._on_changed_cb = on_changed_cb
        self._nautilus_settings = self._try_schema("org.gnome.nautilus.preferences")
        self._fc_settings = self._try_schema("org.gtk.gtk4.Settings.FileChooser")
        self._ext_settings = self._try_ext_schema(EXT_SCHEMA_ID)

        self._fallback_path = os.path.join(
            GLib.get_user_config_dir(), "nautilus-compact-list", "settings.json"
        )
        self._fallback_data = self._load_fallback_json()

        for s in (self._nautilus_settings, self._fc_settings, self._ext_settings):
            if s is not None:
                s.connect("changed", self._on_setting_changed)

    @staticmethod
    def _try_schema(schema_id: str) -> Gio.Settings | None:
        source = Gio.SettingsSchemaSource.get_default()
        if source and source.lookup(schema_id, True):
            return Gio.Settings.new(schema_id)
        return None

    @classmethod
    def _try_ext_schema(cls, schema_id: str) -> Gio.Settings | None:
        # Check default system/user schema source first
        s = cls._try_schema(schema_id)
        if s is not None:
            return s
        # Check ~/.local/share/glib-2.0/schemas if not in XDG_DATA_DIRS
        local_schema_dir = os.path.join(GLib.get_user_data_dir(), "glib-2.0", "schemas")
        if os.path.isdir(local_schema_dir):
            try:
                src = Gio.SettingsSchemaSource.new_from_directory(
                    local_schema_dir, Gio.SettingsSchemaSource.get_default(), False
                )
                schema = src.lookup(schema_id, True)
                if schema is not None:
                    return Gio.Settings.new_full(schema, None, None)
            except GLib.Error:
                pass
        return None

    def _load_fallback_json(self) -> dict:
        try:
            if os.path.isfile(self._fallback_path):
                with open(self._fallback_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_fallback_json(self):
        try:
            os.makedirs(os.path.dirname(self._fallback_path), exist_ok=True)
            with open(self._fallback_path, "w", encoding="utf-8") as f:
                json.dump(self._fallback_data, f, indent=2)
        except Exception:
            pass

    def _on_setting_changed(self, _settings, key: str):
        if self._on_changed_cb:
            self._on_changed_cb(key)

    # --- Extension Persistent State & Settings ---

    @property
    def compact_view_enabled(self) -> bool:
        if self._ext_settings is not None:
            return self._ext_settings.get_boolean("compact-view-enabled")
        return bool(self._fallback_data.get("compact-view-enabled", False))

    @compact_view_enabled.setter
    def compact_view_enabled(self, value: bool):
        val = bool(value)
        self._fallback_data["compact-view-enabled"] = val
        self._save_fallback_json()
        if self._ext_settings is not None:
            if self._ext_settings.get_boolean("compact-view-enabled") != val:
                self._ext_settings.set_boolean("compact-view-enabled", val)
        else:
            self._on_setting_changed(None, "compact-view-enabled")

    @property
    def max_column_width_chars(self) -> int:
        if self._ext_settings is not None:
            return max(15, min(200, self._ext_settings.get_int("max-column-width-chars")))
        return max(15, min(200, int(self._fallback_data.get("max-column-width-chars", 50))))

    @max_column_width_chars.setter
    def max_column_width_chars(self, value: int):
        val = max(15, min(200, int(value)))
        self._fallback_data["max-column-width-chars"] = val
        self._save_fallback_json()
        if self._ext_settings is not None:
            if self._ext_settings.get_int("max-column-width-chars") != val:
                self._ext_settings.set_int("max-column-width-chars", val)
        else:
            self._on_setting_changed(None, "max-column-width-chars")

    @property
    def shortening_mode(self) -> str:
        if self._ext_settings is not None:
            return self._ext_settings.get_string("shortening-mode")
        return str(self._fallback_data.get("shortening-mode", "smart-suffix"))

    @shortening_mode.setter
    def shortening_mode(self, value: str):
        val = str(value)
        self._fallback_data["shortening-mode"] = val
        self._save_fallback_json()
        if self._ext_settings is not None:
            if self._ext_settings.get_string("shortening-mode") != val:
                self._ext_settings.set_string("shortening-mode", val)
        else:
            self._on_setting_changed(None, "shortening-mode")

    # --- Native Nautilus Preferences ---

    @property
    def show_hidden(self) -> bool:
        if self._fc_settings and "show-hidden" in self._fc_settings.list_keys():
            return self._fc_settings.get_boolean("show-hidden")
        if self._nautilus_settings and "show-hidden-files" in self._nautilus_settings.list_keys():
            return self._nautilus_settings.get_boolean("show-hidden-files")
        return False

    @property
    def single_click_activate(self) -> bool:
        if self._nautilus_settings:
            return self._nautilus_settings.get_string("click-policy") == "single"
        return False

    @property
    def sort_directories_first(self) -> bool:
        if self._fc_settings:
            return self._fc_settings.get_boolean("sort-directories-first")
        return True

    @property
    def sort_order(self) -> str:
        if self._nautilus_settings:
            return self._nautilus_settings.get_string("default-sort-order")
        return "name"

    @property
    def icon_size(self) -> int:
        if self._ext_settings is not None and "icon-size" in self._ext_settings.list_keys():
            val = self._ext_settings.get_int("icon-size")
            if val in (16, 32, 64):
                return val
        val = int(self._fallback_data.get("icon-size", 16))
        return val if val in (16, 32, 64) else 16

    @icon_size.setter
    def icon_size(self, value: int):
        val = int(value) if int(value) in (16, 32, 64) else 16
        self._fallback_data["icon-size"] = val
        self._save_fallback_json()
        if self._ext_settings is not None and "icon-size" in self._ext_settings.list_keys():
            if self._ext_settings.get_int("icon-size") != val:
                self._ext_settings.set_int("icon-size", val)
        else:
            self._on_setting_changed(None, "icon-size")

    @property
    def sort_reversed(self) -> bool:
        if self._nautilus_settings:
            return self._nautilus_settings.get_boolean("default-sort-in-reverse-order")
        return False

