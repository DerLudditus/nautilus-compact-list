# Technical Architecture: `nautilus-compact-list`

This document describes the internal design, runtime GTK4 widget-tree injection mechanics, multi-column layout engine, native state bridging, and cross-desktop integration of **`nautilus-compact-list`**. It serves as a technical guide for contributors and developers unfamiliar with GNOME Files (Nautilus) internals or `nautilus-python` runtime extensions. It was known to be accurate for version 0.1.0-20.

---

## 1. Core Concepts & Design Philosophy

### 1.1. The Problem: Limitations of `libnautilus-extension` in GTK4
When GNOME 43 migrated Nautilus from GTK3 to GTK4 and `libadwaita`, the legacy `Nautilus.LocationWidgetProvider` interface was removed. Officially, `libnautilus-extension` now restricts extensions to passive hooks:
- Adding context menu entries (`Nautilus.MenuProvider`)
- Adding custom list attributes (`Nautilus.ColumnProvider`, `Nautilus.InfoProvider`)
- Adding properties page models (`Nautilus.PropertiesModelProvider`)

There is no official public API for registering a custom directory view mode (like the classic multi-column Compact List view found in GNOME 2 Nautilus, Caja, Thunar, Dolphin, or PCManFM).

### 1.2. The Solution: In-Process GTK4 Widget-Tree Injection
Although `libnautilus-extension` is restricted, `nautilus-python` executes Python extensions **in-process** inside the main `nautilus` executable. Consequently, the extension shares:
- The process memory space and GObject type system (`GType`)
- The default `Gdk.Display`, `Gtk.Application`, and GLib main event loop
- Full introspection access (`PyGObject`) to every live GTK4 widget in every open window

`nautilus-compact-list` registers a minimal `Nautilus.MenuProvider` (`NautilusCompactListExtension`) solely as an entry point. Once loaded, it schedules an idle controller (`CompactListExtensionController`) that discovers `NautilusWindow` instances, upgrades the headerbar's 2-way view toggle into a 3-segment switcher (`[ Grid | List | Compact ]`), and attaches a custom `CompactListView` page directly inside each tab's `NautilusWindowSlot` `Gtk.Stack`—all **without binary patches or recompiling Nautilus**.

```text
+---------------------------------------------------------------------------------------+
| Nautilus Process (GTK4 / Libadwaita / C State Machine)                                |
|                                                                                       |
|  +---------------------------------------------------------------------------------+  |
|  | AdwHeaderBar -> NautilusViewControls (AdwBin)                                   |  |
|  |   +---------------------------------------------------------------------------+ |  |
|  |   | Injected Gtk.Box                                                          | |  |
|  |   |  * CompactListToggleButton: [ Grid | List | Compact ] (3-segment pill)    | |  |
|  |   |  * Gtk.MenuButton ("view-more-symbolic"): View Options + Icon Size row    | |  |
|  |   |  * Native Adw.SplitButton (set_visible(False) — kept alive for state sync)| |  |
|  |   +---------------------------------------------------------------------------+ |  |
|  +---------------------------------------------------------------------------------+  |
|                                                                                       |
|  +---------------------------------------------------------------------------------+  |
|  | Adw.TabView -> NautilusWindowSlot (Active Tab) -> Slot Gtk.Stack                |  |
|  |                                                                                 |  |
|  |   +-------------------------------------+  +----------------------------------+ |  |
|  |   | Native Child (NautilusFilesView)    |  | Stack Page: "compact-list"       | |  |
|  |   | * Kept alive in Gtk.Stack           |  | (CompactListView - Gtk.Box)      | |  |
|  |   | * Owns C state machine & GActions   |  |  +-- Adw.Banner (Special dirs)   | |  |
|  |   | * Owns NautilusViewModel selection  |  |  +-- Gtk.Stack (_view_stack)     | |  |
|  |   +-------------------------------------+  |  |    +-- "scrolled": Columns    | |  |
|  |                      ^                     |  |    +-- "empty": Adw.StatusPage| |  |
|  |                      | Selection Bitset    |  +-- .compact-status-bar         | |  |
|  |                      +---------------------+      (Localized counts & space)  | |  |
|  |                        & GAction Forwarding+----------------------------------+ |  |
|  +---------------------------------------------------------------------------------+  |
|                                                                                       |
|  +---------------------------+  +--------------------------+  +--------------------+  |
|  | StyleMetrics              |  | NautilusPrefs            |  | i18n & ContextMenu |  |
|  | * Parses Nautilus CSS &   |  | * GSettings schema +     |  | * Native gettext + |  |
|  |   ~/.config/gtk-4.0/      |  |   JSON fallback          |  |   28-locale catalog|  |
|  +---------------------------+  +--------------------------+  +--------------------+  |
+---------------------------------------------------------------------------------------+
```

---

## 2. Repository & Module Structure

```text
nautilus-compact-list/
├── nautilus-compact-list.py           # Entry point implementing Nautilus.MenuProvider
├── version.py                         # Single source of truth for version & changelog
├── io.github.nautilus-compact-list.gschema.xml  # GSettings schema definition
├── nautilus_compact_list/
│   ├── __init__.py                    # Exposes __version__ from root version.py
│   ├── main.py                        # CompactListExtensionController & SlotAttachment
│   ├── compact_view.py                # CompactListView widget, layout, input & status bar
│   ├── file_view_menu.py              # CompactListToggleButton & headerbar injection
│   ├── context_menu.py                # Right-click menus, inline popovers, terminal launch
│   ├── native_selection.py            # NautilusViewModel bitset sync & URI activation
│   ├── style_metrics.py               # Runtime Nautilus CSS extraction & metric parser
│   ├── shortener.py                   # Suffix-aware smart filename truncation engine
│   ├── nautilus_prefs.py              # Dual-layer GSettings / JSON configuration manager
│   ├── i18n.py                        # Zero-overhead 28-language translation catalog
│   ├── common.py                      # GTK4 widget walkers, slot watchers, base CSS, logging
│   └── icons/
│       └── view-compact-symbolic.svg  # 16x16 symbolic SVG icon for the headerbar switcher
├── build-deb.sh                       # Universal .deb builder (dpkg-deb / dpkg-buildpackage)
├── build-rpm.sh                       # Universal .rpm builder (isolated rpmbuild)
├── debian/                            # Debian packaging metadata
└── packaging/rpm/                     # Fedora/RHEL RPM spec file
```

---

## 3. Runtime GTK4 Injection Mechanics

### 3.1. Window Discovery & Settling (`main.py`, `common.py`)
Nautilus windows can be opened at startup, via D-Bus activation, or mid-session. `CompactListExtensionController` discovers windows through three redundant mechanisms:
1. **Toplevel Enumeration**: Scans `Gtk.Window.list_toplevels()` on startup and via a 1000 ms periodic timer (`_periodic_sync`).
2. **Application Signal**: Connects to the `window-added` signal on `Gtk.Application.get_default()`.
3. **Navigation Pulse**: Hooks `Nautilus.MenuProvider.get_background_items()` to trigger an idle window sync whenever the user changes folders.

Windows are verified via `_is_nautilus_window()` using a layered check: `buildable_id == "NautilusWindow"`, class name `"NautilusWindow"`, CSS class `"nautilus-window"`, presence of `Adw.OverlaySplitView`, or descendant `NautilusWindowSlot` / `NautilusViewControls` widgets.

Before injecting widgets into a newly detected window, `_schedule_window_init()` polls every 20 ms (up to 50 attempts) until the window is mapped (`win.get_mapped()`) and its title no longer contains `"Loading"` or `"…"`, ensuring Nautilus has finished constructing its internal widget hierarchy.

### 3.2. Headerbar 3-Segment View Switcher (`file_view_menu.py`)
In modern GTK4 Nautilus, the view mode control resides inside `NautilusViewControls` (an `Adw.Bin` in the headerbar) and consists of a single `Adw.SplitButton`: clicking the main button toggles between Grid and List (`slot.files-view-mode-toggle`), while clicking the dropdown arrow opens the View Options menu.

`inject_view_switcher()` transforms this control into a 3-segment switcher while preserving the View Options menu:
1. **Locating the Native Control**: `find_split_button()` locates the `Adw.SplitButton` inside `NautilusViewControls` (or by matching action name `"slot.files-view-mode-toggle"`).
2. **Non-Destructive Hiding**: The native `split_button` is hidden (`split_button.set_visible(False)`), marked with `_compact_switcher_injected = True`, and kept parented inside the replacement container so its `icon-name` property and menu model remain live.
3. **Building the Replacement Controls**:
   - **`CompactListToggleButton`**: A custom `Gtk.Box` (`.mc-toggle-group`) containing three grouped flat `Gtk.ToggleButton` segments (`grid`, `list`, `compact`) separated by 1 px vertical `Gtk.Separator` widgets (`.mc-toggle-sep`). Motion controllers track hover state so separators automatically fade out (`opacity: 0`) when an adjacent segment is active or hovered.
   - **View Options Button**: A `Gtk.MenuButton` (`view-more-symbolic`) bound to a `Gtk.PopoverMenu` constructed from `split_button.get_menu_model()` (or `_build_fallback_options_model()` if unavailable), with a custom `"icon-size-row"` widget (`zoom-out` / `zoom-in` buttons bound to `view.zoom-out` and `view.zoom-in`) injected at the top.
4. **Bidirectional State Synchronization**:
   - In Nautilus, the native `split_button` icon shows the *alternate* view mode: when Nautilus is in **List View**, `split_button.get_icon_name()` is `"view-grid-symbolic"`; when in **Grid View**, it is `"view-list-symbolic"`.
   - Connecting to `split_button.connect("notify::icon-name", ...)` and `Adw.TabView.connect("notify::selected-page", ...)` keeps the 3-segment button in sync with native shortcuts (`Ctrl+1`, `Ctrl+2`) and tab changes.
   - Clicking **Grid** or **List** in `CompactListToggleButton` deactivates Compact View and, if the underlying native view is currently on the opposite mode, dispatches `win.activate_action("slot.files-view-mode-toggle", None)`.

### 3.3. Non-Destructive Slot Stack Management (`SlotAttachment` in `main.py`)
Each tab in Nautilus is represented by a `NautilusWindowSlot`. Inside every `NautilusWindowSlot` is a top-level `Gtk.Stack` (`self->stack` in `nautilus-window-slot.c`) that holds the active `NautilusFilesView` (`NautilusListBase` / Grid / List).

**Critical Constraint**: The native `NautilusFilesView` must **never** be destroyed or unparented. Nautilus's C state machine, background directory monitoring, D-Bus operations, and window-level `GAction` routing depend on `NautilusFilesView` remaining realized inside the slot.

`watch_slots()` enumerates existing pages in `Adw.TabView` and subscribes to `page-attached` for new tabs. Once a slot's `"location"` GObject property resolves (`schedule_slot_init()`), `SlotAttachment` performs the following:
1. Caches a pointer to the slot stack's initial visible child (`self._previous_child`).
2. Adds `CompactListView` to the slot's `Gtk.Stack` as a named page: `stack.add_named(self.compact_view, "compact-list")`.
3. Binds the hidden native `NautilusFilesView` reference to `CompactListView` (`compact_view.bind_native_view(files_view)`).
4. **View Reassertion (`_on_visible_child_changed`)**: When the user navigates to a new folder, Nautilus's C code automatically resets the slot's `Gtk.Stack` visible child back to the native `NautilusFilesView`. `SlotAttachment` listens to `notify::visible-child` on the `Gtk.Stack` and immediately switches visibility back to `compact_view` (guarded by `self._reasserting`), **except** when:
   - The stack switches to `"global_search_page"` (allowing native global search to function).
   - The user navigates to a special virtual URI (`recent:`, `starred:`, `trash:`, `network:`, `x-nautilus-search:`), where native specialized UI controls are required.

---

## 4. Dynamic Layout, Geometry & Auto-Scroll Engine (`compact_view.py`)

### 4.1. Internal Widget Hierarchy of `CompactListView`
`CompactListView` (subclass of vertical `Gtk.Box`) arranges three vertical regions:
1. **Contextual Top Banner (`Adw.Banner`)**: Automatically revealed when browsing special XDG/Nautilus directories (`~/Templates`, `~/.local/share/nautilus/scripts`, or `~/Public`), displaying Nautilus's native localized guidance strings and a `"Learn More"` help launcher (`help:gnome-help/files-templates`).
2. **Main View Stack (`Gtk.Stack` — `_view_stack`)**:
   - `"scrolled"`: A `Gtk.ScrolledWindow` containing `_columns_box` (horizontal `Gtk.Box`), which holds one vertical `Gtk.Box` (`.compact-list-column`) per column.
   - `"empty"`: An `Adw.StatusPage` (with `folder-symbolic` icon and localized `"Folder is Empty"` title) shown automatically when a directory contains zero visible entries.
3. **Bottom Status Bar (`Gtk.Box` — `.compact-status-bar`)**: Displays live directory or selection statistics.

### 4.2. Asynchronous Directory Enumeration & Sorting
When `load_location(gfile)` is called:
1. Any in-flight `Gio.Cancellable` is cancelled, and a new `Gio.FileMonitor` (`monitor_directory`) is attached to trigger `reload()` on filesystem changes.
2. Free disk space is queried via `gfile.query_filesystem_info(Gio.FILE_ATTRIBUTE_FILESYSTEM_FREE, None)`.
3. `gfile.enumerate_children_async()` fetches standard file attributes (`name`, `display-name`, `type`, `icon`, `is-hidden`, `size`, `time::modified`).
4. Entries are filtered by `prefs.show_hidden` and sorted by `_sort_entries()` according to native Nautilus preferences (`sort_order` by casefolded display name, size, or mtime; `sort_reversed`; and `sort_directories_first`).
5. If a file was just created from a template (`_pending_select_name`), it is automatically selected upon enumeration completion.

### 4.3. Viewport Bounding & Multi-Column Flow Mathematics
To prevent GTK4 from expanding the `Gtk.ScrolledWindow` vertically to fit all items in a single infinite column, `_scrolled` is configured with:
- **Horizontal Policy**: `Gtk.PolicyType.AUTOMATIC`
- **Vertical Policy**: `Gtk.PolicyType.EXTERNAL` (bounds the child allocation strictly to the visible viewport height while suppressing vertical scrollbars)

Rather than using resize-sensor overlay hacks, `CompactListView` connects directly to the vertical adjustment's page size signal (`vadjustment.connect("notify::page-size", _on_vadjustment_page_size_changed)`).

Given viewport height $H$ (`vadj.get_page_size()`), top padding $P_{\text{top}}$, bottom padding $P_{\text{bottom}}$, measured row height $h$ (`row_widgets[0].measure(Gtk.Orientation.VERTICAL, -1)`), and vertical border spacing $s$ (`4px` in compact 16px mode, `8px` in 32px/64px mode):

$$\text{Row Pitch } p = \max(1,\; h + s)$$

$$\text{Usable Height } H_{\text{usable}} = \max(p,\; H - P_{\text{top}} - P_{\text{bottom}})$$

$$\text{Rows Per Column } R = \max\left(1,\; \left\lfloor \frac{H_{\text{usable}} + s}{p} \right\rfloor\right)$$

Entries are sliced into chunks of $R$ items. Item $i$ resides at column $c = \lfloor i / R \rfloor$ and row $r = i \bmod R$, flowing top-to-bottom within each column and wrapping left-to-right across columns.

### 4.4. Variable-Width Columns & Exact Pango Pill Measurement
Each column is a vertical `Gtk.Box` whose width naturally shrinks or expands to fit the longest filename in *that specific column* (up to `max_column_width_chars`, default `50`).

When clicking or navigating via keyboard to an item in a partially visible column near the right or left edge of the viewport, `_ensure_index_visible(index)` scrolls **only as much as needed** to reveal that specific item's selection pill rather than jumping by the entire width of the column:
1. `_get_item_pill_width(row)` computes the exact rendered width of the individual row's selection pill:
   - Measures the `Gtk.Image` icon width (`img.measure()`).
   - Queries the exact rendered pixel width of the text přímo from the `Gtk.Label`'s Pango layout: `lbl.get_layout().get_pixel_size()` (falling back to `lbl.measure()` or character heuristic if unrealized).
   - Sums the full pill geometry:
     $$W_{\text{pill}} = P_x + W_{\text{icon}} + \text{spacing} + W_{\text{label}} + P_x$$
2. Using `row.compute_bounds(self._columns_box)`, if `row_left + pill_w + 24px > view_right` (or `row_left - 24px < view_left`), `hadjustment` is shifted by the exact delta required to keep a `24px` breathing margin from the viewport border.

### 4.5. Mouse-Wheel Translation & Independent Icon Zoom
A `Gtk.EventControllerScroll` (`BOTH_AXES`) on `_scrolled` handles both horizontal panning and icon zooming:
- **Unmodified Scroll**: Intercepts vertical scroll delta ($dy$) or horizontal delta ($dx$) and pans `hadjustment` horizontally by $\text{delta} \times \max(60.0, \text{step\_increment})$.
- **`Ctrl+Scroll` / `Shift+Scroll`** (as well as `Ctrl++`, `Ctrl+-`, `Ctrl+0`, and the headerbar View Options zoom buttons): Cycles `prefs.icon_size` across three discrete tiers matching Nautilus's List View C backend: **16 px** (compact cells), **32 px** (normal cells), and **64 px** (normal cells). Font size remains fixed at the system desktop default across all zoom tiers, and the zoom level is stored independently of Nautilus's native List and Grid views.

---

## 5. Dynamic CSS & Style Metrics System (`style_metrics.py`, `common.py`)

To ensure 1:1 visual parity with Nautilus's native List View across different themes and fractional scaling factors (100%, 125%, 150%), `style_metrics.py` extracts and parses Nautilus's compiled stylesheet at runtime:

1. **CSS Acquisition (`_load_raw_css`)**:
   - **Primary (In-Process)**: Calls `Gio.resources_lookup_data("/org/gnome/nautilus/style.css", Gio.ResourceLookupFlags.NONE)` directly in memory.
   - **Secondary (CLI Fallback)**: Runs `gresource extract /usr/bin/nautilus /org/gnome/nautilus/style.css` when invoked outside the Nautilus process (e.g., during standalone tests).
   - **User Overrides**: Appends `~/.config/gtk-4.0/gtk.css` if present.
2. **Parsed Selectors & Metrics (`StyleMetrics`)**:
   - `.nautilus-list-view columnview`: `padding-left` (default `24px`), `padding-right` (minimum `48px` to prevent rightmost column clipping under fractional scaling).
   - `.nautilus-list-view columnview > listview`: `padding-top` (capped at `12px`), `padding-bottom` (fixed at `6px` above the status bar to maximize usable column height and avoid empty bottom voids), and `border-spacing` (`8px` normal).
   - `.nautilus-list-view.compact columnview > listview`: `border-spacing` (`4px` compact).
   - `.nautilus-list-view columnview > listview > row`: `border-radius` (`9px` selection pill rounding).
   - `.nautilus-list-view #NautilusViewCell` & `.compact #NautilusViewCell`: Cell padding `(6px, 6px)` for 32px/64px icons and `(3px, 6px)` for 16px icons.

`ensure_resources_loaded()` in `common.py` combines base semantic color rules (`@view_bg_color`, `@view_fg_color`, `@accent_bg_color`, `@accent_fg_color`, `.compact-status-bar`, `.mc-toggle-*`) with `StyleMetrics.generate_css()` and registers them at `Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION`.

---

## 6. Selection Bridging, Clipboard & Native Action Dispatch (`native_selection.py`, `compact_view.py`)

### 6.1. Selection Model Synchronization (`sync_selection_to_native`)
Nautilus's internal C actions (`view.move-to-trash`, `view.delete-permanently-shortcut`, `view.properties`, `view.open-item-new-tab`) operate on whatever items are selected in the native view's `NautilusViewModel`.

Whenever selection changes in `CompactListView`:
1. `get_native_selection_model()` walks the hidden `NautilusFilesView` to find its internal `Gtk.ListView`, `Gtk.GridView`, or `Gtk.ColumnView` and retrieves its selection model (`NautilusViewModel`).
2. `sync_selection_to_native()` normalizes the selected URIs, iterates through the native model's items (unwrapping `Gtk.TreeListRow` if needed and reading `"file"` or `"uri"` properties), and builds a `Gtk.Bitset` of matching indices.
3. It applies the selection atomically via `model.set_selection(selected_bitset, Gtk.Bitset.new_range(0, n_items))`.

### 6.2. Dual-Format Clipboard & D-Bus File Operations
When `CompactListView` has keyboard focus, window-level shortcuts (`Ctrl+C`, `Ctrl+X`, `Ctrl+V`, `Ctrl+A`) are routed to a `"view"` `Gio.SimpleActionGroup` registered directly on `CompactListView`:
- **Copy / Cut (`copy_to_clipboard`)**: Populates the system `Gdk.Clipboard` with a `Gdk.ContentProvider.new_union()` containing both:
  1. A boxed `Gdk.FileList` (modern GTK4 / portal clipboard standard).
  2. Raw bytes for MIME type `x-special/gnome-copied-files` (`"copy\nfile://..."` or `"cut\nfile://..."`, required by classic GNOME/XFCE/MATE file managers).
  It also synchronizes selection and triggers `view.copy` / `view.cut` on the hidden native view.
- **Paste (`paste_from_clipboard`)**: First attempts to trigger `view.paste` / `view.paste-into` on the native view. If unavailable, it reads `Gdk.FileList` from the clipboard asynchronously and invokes Nautilus's native D-Bus service (`org.gnome.Nautilus.FileOperations2` `CopyURIs` / `MoveURIs` on `/org/gnome/Nautilus/FileOperations2`) so native progress bars and conflict dialogs are used, falling back to `Gio.File.copy()` / `move()` only if D-Bus fails.
- **Trash & Permanent Delete**: `Delete` dispatches `view.move-to-trash` on the native view (falling back to `Gio.File.trash()` if needed). `Shift+Delete` dispatches `view.delete-permanently-shortcut`, invoking Nautilus's native confirmation dialog.
- **Directory & File Activation (`activate_uri_in_native_view`)**:
  - **Directories**: Activated in-place via `slot.open-location` (or `win.open-location`) with a string `GLib.Variant(uri)`.
  - **Files**: Launched via `Gio.AppInfo.launch_default_for_uri(uri, None)` with `Gtk.UriLauncher` as a fallback.

---

## 7. Context Menus, Inline Popovers & Cross-Desktop Terminal Resolution (`context_menu.py`)

### 7.1. Item & Background Context Menus
`CompactContextMenu` attaches a `"compact"` `Gio.SimpleActionGroup` to `CompactListView` and displays a `Gtk.PopoverMenu` anchored to the cursor coordinates:
- **Item Context Menu**: `Open`, `Open in New Tab` (for single folders), `Cut`, `Copy`, `Rename…` (`F2`), `Move to Trash`, `Delete Permanently…`, and `Properties`.
- **Background Context Menu**: `New Folder…`, `New Document` (dynamically built recursive submenu from `~/Templates` that copies the selected template with automatic `name (2).ext` collision numbering and auto-selects the new file), `Paste`, `Select All`, `Set Max Column Width…`, `Open in Terminal` / `Open in Console`, and folder `Properties`.
- **Inline Popovers**: `Rename…` (pre-selecting only the filename stem before the extension), `New Folder…`, and `Set Max Column Width…` (15–200 char `Gtk.SpinButton`) are implemented as lightweight inline `Gtk.Popover` dialogs.
- **Properties Dialog**: Triggers `view.properties` on the native view and invokes `org.freedesktop.FileManager1.ShowItemProperties` over session D-Bus to guarantee the native Properties window opens.

### 7.2. Cross-Desktop Terminal Discovery Hierarchy
When Nautilus is installed on non-GNOME desktops (such as XFCE, KDE Plasma, MATE, or Cinnamon), its native views often omit the `"Open in Terminal"` context menu entry if `gnome-console` (`kgx`) or `ptyxis` is not installed. `CompactContextMenu` provides environment-aware terminal labeling (`get_terminal_menu_label()`) and a strict 4-tier execution hierarchy (`_on_open_terminal()`):

1. **Ubuntu & GNOME Priority**:
   - On Ubuntu sessions (`is_ubuntu_system()` via `XDG_CURRENT_DESKTOP` or `/etc/os-release`), prioritizes `gnome-terminal` first.
   - Queries `org.gnome.desktop.default-applications.terminal` (`exec` key) if not set to generic `x-terminal-emulator`.
   - Probes native GNOME terminal binaries (`("gnome-terminal", "ptyxis", "kgx")` on Ubuntu; `("ptyxis", "kgx", "gnome-terminal")` on Fedora / upstream GNOME).
2. **Active Desktop Environment Native Terminal**:
   - **KDE Plasma**: Queries `kreadconfig6` / `kreadconfig5` (`kdeglobals` $\rightarrow$ `[General]` $\rightarrow$ `TerminalApplication`), parses `~/.config/kdeglobals` directly via `configparser`, or falls back to `konsole`.
   - **XFCE**: Spawns `exo-open --working-directory <workdir> --launch TerminalEmulator`.
   - **Cinnamon**: Queries `org.cinnamon.desktop.default-applications.terminal`.
   - **MATE**: Queries `org.mate.applications-terminal`.
3. **Freedesktop Standard**: Spawns `xdg-terminal-exec --dir <workdir>`.
4. **System Fallback**: Spawns `x-terminal-emulator` with the working directory set via `Gio.SubprocessLauncher.set_cwd(workdir)`.

---

## 8. Localization Architecture (`i18n.py`, `compact_view.py`, `context_menu.py`)

Localization is split into two zero-build-overhead layers so the extension requires no compiled `.mo`/`.po` files of its own:

1. **System Translation Reuse (`GLib.dgettext` / `GLib.dngettext` & UI Resource Extraction)**:
   - **Context Menu Labels**: `get_native_menu_label()` loads `/org/gnome/nautilus/ui/nautilus-files-view-context-menus.ui` into a `Gtk.Builder` with translation domain `"nautilus"` and extracts the exact localized strings used by Nautilus's native menus.
   - **Status Bar & Banners**: Uses `GLib.dngettext("nautilus", ...)` for plural-aware folder/file/selection counts (`"%'u folder"`, `"%'u file"`, `"%'d item selected"`, `"%s Free"`) and `GLib.format_size_full(..., GLib.FormatSizeFlags.IEC_UNITS)` for localized binary units (`KiB`/`MiB`/`GiB`, or `Kio`/`Mio`/`Gio` in French).
2. **In-Tree Catalog for Extension-Specific Strings (`i18n.py`)**:
   - The three custom UI strings introduced by the extension (`"Set Max Column Width…"`, `"Max chars:"`, and `"Apply"`) are translated in-tree across **28 locales** (`fr`, `de`, `es`, `it`, `pt`, `ru`, `pl`, `nl`, `sv`, `nb`, `nn`, `da`, `fi`, `cs`, `hu`, `tr`, `ro`, `el`, `uk`, `ja`, `zh_cn`, `zh_tw`, `ko`, `ar`, `he`, `id`, `ca`, `hi`).
   - `_t(msg)` inspects `LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, and `LANG`, matching full regional tags (`zh_cn`, `zh_tw`) first and language prefixes (`fr`, `de`, `ro`, etc.) second.

---

## 9. Smart Suffix-Aware Filename Shortener (`shortener.py`)

To prevent long filenames from blowing out column widths, `shorten_filename(filename, max_chars=50, mode="smart-suffix", stem_context_chars=2)` truncates names exceeding `max_chars` while preserving identifying suffixes:

1. **Compound Extension & Dotfile Splitting (`split_filename_stem_ext`)**:
   - Recognizes compound extensions (`.tar.gz`, `.tar.xz`, `.tar.bz2`, `.tar.zst`, `.dpkg-old`, `.dpkg-dist`, `.dpkg-new`) as atomic extensions.
   - Treats single-dot leading dotfiles (e.g., `.bashrc`) as pure stems with no extension.
2. **Truncation Modes**:
   - **`'smart-suffix'` (Default)**:
     - Tests the stem against `_NUMERIC_OR_DATE_TAIL_RE`, which matches trailing copy counters (` (1)`, ` (17)`, `_[2]`) and numeric/date/timestamp tails (`1`, `_20260102`, `_2026-01-02`, `-2026-01-02_14-30`).
     - **With Numeric/Date Tail**: Preserves the last 2 characters of the base word stem + the entire numeric/date suffix + the extension:
       `looooooooooooooooooooooongfilename (17).txt` $\rightarrow$ `looooooooooooooooooooo...me (17).txt`
     - **Without Numeric/Date Tail**: Preserves the extension after `"..."`:
       `looooooooooooooooooooooongfilename_long.txt` $\rightarrow$ `looooooooooooooooooooooongfilena....txt`
   - **`'middle'`**: Standard 55% prefix / 45% suffix middle ellipsis.
3. **Full Filename Tooltip**: Whenever `short_label != entry.display_name`, `CompactListView` attaches the full unshortened filename as a hover tooltip on the row widget (`row.set_tooltip_text(entry.display_name)`).

---

## 10. Dual-Layer Configuration & Packaging (`nautilus_prefs.py`, `version.py`)

### 10.1. Dual-Layer Settings Persistence (`NautilusPrefs`)
`NautilusPrefs` manages four extension settings (`compact-view-enabled`, `max-column-width-chars`, `shortening-mode`, `icon-size`) alongside native preferences from `org.gnome.nautilus.preferences` and `org.gtk.gtk4.Settings.FileChooser`:
- **Layer 1 (GSettings)**: Looks up `io.github.nautilus-compact-list` in the system `Gio.SettingsSchemaSource` and in `~/.local/share/glib-2.0/schemas`.
- **Layer 2 (JSON Fallback)**: Every setter simultaneously persists values to `~/.config/nautilus-compact-list/settings.json`. If the GSettings schema is not compiled in a minimal or non-GNOME environment, the extension reads and writes seamlessly from the JSON file.

### 10.2. Single-Source Versioning & Packaging (`version.py`, `build-deb.sh`, `build-rpm.sh`)
- **`version.py`**: Centralizes `__version__`, `DEB_VERSION`, maintainer metadata, and `CHANGELOG`.
- **`build-deb.sh` (`make deb`)**: Reads `version.py`, auto-generates `debian/changelog`, and builds a universal architecture-independent `.deb` (`dist/nautilus-compact-list_<version>_all.deb`) via fast self-contained `dpkg-deb` staging (default) or `dpkg-buildpackage` (`--dpkg-buildpackage`), including `postinst`/`postrm` hooks to compile GSettings schemas.
- **`build-rpm.sh` (`make rpm`)**: Reads `version.py` and builds a universal `.noarch.rpm` (`dist/nautilus-compact-list-<version>.noarch.rpm`) using `rpmbuild` with isolated `_topdir`, `_tmppath`, and `_dbpath` so RPMs can be built cleanly on both Fedora and Debian/Ubuntu hosts.
- **Diagnostics**: Setting `NAUTILUS_COMPACT_LIST_DEBUG=1` enables timestamped, PID-tagged debug logging to both `stderr` and `/tmp/nautilus-compact-list.log` (completely silent by default).

---
