import os
import sys
import gi

gi.require_version("Gtk", "4.0")
try:
    gi.require_version("Adw", "1")
except (ValueError, AttributeError):
    pass

from gi.repository import GObject, GLib

try:
    gi.require_version("Nautilus", "4.0")
except (ValueError, AttributeError):
    pass

try:
    from gi.repository import Nautilus
except (ImportError, ValueError):
    # Standalone or test environment fallback
    class _MockMenuProvider:
        pass

    class _MockNautilus:
        MenuProvider = _MockMenuProvider

    Nautilus = _MockNautilus()

EXT_DIR = os.path.dirname(os.path.abspath(__file__))
if EXT_DIR not in sys.path:
    sys.path.insert(0, EXT_DIR)

from nautilus_compact_list.common import log
from nautilus_compact_list.main import CompactListExtensionController

log(f"Extension script loaded from {__file__}")


class NautilusCompactListExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        super().__init__()
        log("NautilusCompactListExtension.__init__ called")
        self._controller = None
        GLib.idle_add(self._init_controller)

    def _init_controller(self):
        try:
            if self._controller is None:
                log("Initializing CompactListExtensionController...")
                self._controller = CompactListExtensionController()
                log("CompactListExtensionController successfully initialized")
        except Exception as exc:
            log(f"ERROR initializing controller: {exc!r}")
        return GLib.SOURCE_REMOVE

    def get_background_items(self, current_folder):
        if self._controller is not None and current_folder is not None:
            GLib.idle_add(self._controller.sync_windows)
        return []

    def get_file_items(self, files):
        return []

