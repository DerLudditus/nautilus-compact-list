from dataclasses import dataclass
import os
import re
import subprocess


def parse_px(val, default: int | None) -> int | None:
    if not val:
        return default
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*px", str(val))
    if m:
        return int(round(float(m.group(1))))
    return default


def parse_padding(val, default: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    if not val:
        return default
    parts = val.split()
    nums = [parse_px(p, None) for p in parts if parse_px(p, None) is not None]
    if len(nums) == 1:
        return (nums[0], nums[0])
    if len(nums) >= 2:
        return (nums[0], nums[1])
    return default


@dataclass(frozen=True)
class StyleMetrics:
    padding_left: int = 24
    padding_right: int = 48
    padding_top: int = 12
    padding_bottom: int = 6
    border_spacing_normal: int = 8
    border_spacing_compact: int = 4
    border_radius: int = 9
    cell_padding_normal: tuple[int, int] = (6, 6)
    cell_padding_compact: tuple[int, int] = (3, 6)

    def get_border_spacing(self, is_compact: bool) -> int:
        return self.border_spacing_compact if is_compact else self.border_spacing_normal

    def get_cell_padding(self, is_compact: bool) -> tuple[int, int]:
        return self.cell_padding_compact if is_compact else self.cell_padding_normal

    def generate_css(self) -> str:
        """Generates dynamic CSS rules using the exact metrics parsed from Nautilus theme."""
        norm_y, norm_x = self.cell_padding_normal
        comp_y, comp_x = self.cell_padding_compact
        return f"""
.compact-list-columns {{
    padding: {self.padding_top}px {self.padding_right}px {self.padding_bottom}px {self.padding_left}px;
}}
.compact-list-column {{
    margin-right: {self.padding_left}px;
}}
.compact-list-row {{
    border-radius: {self.border_radius}px;
}}
.compact-list-row.compact-cell {{
    padding: {comp_y}px {comp_x}px;
}}
.compact-list-row.normal-cell {{
    padding: {norm_y}px {norm_x}px;
}}
"""


def _load_raw_css() -> str:
    # 1. In-process GResource lookup when running inside Nautilus
    try:
        from gi.repository import Gio
        data = Gio.resources_lookup_data(
            "/org/gnome/nautilus/style.css", Gio.ResourceLookupFlags.NONE
        )
        if data:
            return data.get_data().decode("utf-8")
    except Exception:
        pass

    # 2. Extract from /usr/bin/nautilus binary via gresource tool
    nautilus_bin = "/usr/bin/nautilus"
    if os.path.isfile(nautilus_bin):
        try:
            res = subprocess.run(
                ["gresource", "extract", nautilus_bin, "/org/gnome/nautilus/style.css"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout:
                return res.stdout
        except Exception:
            pass

    return ""


def _parse_css_rules(css_text: str) -> dict[str, dict[str, str]]:
    if not css_text:
        return {}
    clean_text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    rules: dict[str, dict[str, str]] = {}
    for block in re.finditer(r"([^{]+)\{([^}]+)\}", clean_text):
        selectors = [s.strip() for s in block.group(1).split(",")]
        decls: dict[str, str] = {}
        for d in block.group(2).split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip().lower()] = v.strip()
        for sel in selectors:
            clean_sel = " ".join(sel.split())
            rules.setdefault(clean_sel, {}).update(decls)
    return rules


def load_style_metrics() -> StyleMetrics:
    """Reads and parses layout metrics directly from Nautilus's CSS and user theme overrides."""
    css = _load_raw_css()

    user_gtk_css = os.path.expanduser("~/.config/gtk-4.0/gtk.css")
    if os.path.isfile(user_gtk_css):
        try:
            with open(user_gtk_css, "r", encoding="utf-8") as f:
                css += "\n" + f.read()
        except Exception:
            pass

    rules = _parse_css_rules(css)
    if not rules:
        return StyleMetrics()

    col_view = rules.get(".nautilus-list-view columnview", {})
    pad_l = parse_px(col_view.get("padding-left"), 24) or 24
    pad_r = max(48, parse_px(col_view.get("padding-right"), 48) or 48)

    list_view = rules.get(".nautilus-list-view columnview > listview", {})
    pad_t = min(parse_px(list_view.get("padding-top"), 12) or 12, 12)
    pad_b = 6  # Compact view has a bottom status bar; 6px breathing room avoids empty bottom voids
    sp_norm = parse_px(list_view.get("border-spacing"), 8) or 8

    compact_list = rules.get(".nautilus-list-view.compact columnview > listview", {})
    sp_comp = parse_px(compact_list.get("border-spacing"), 4) or 4

    row_rule = rules.get(".nautilus-list-view columnview > listview > row", {})
    radius = parse_px(row_rule.get("border-radius"), 9) or 9

    norm_cell = rules.get(".nautilus-list-view #NautilusViewCell", {})
    cell_norm = parse_padding(norm_cell.get("padding"), (6, 6))

    comp_cell = rules.get(".nautilus-list-view.compact #NautilusViewCell", {})
    comp_top = parse_px(comp_cell.get("padding-top"), 3) or 3
    cell_comp = (comp_top, cell_norm[1])

    return StyleMetrics(
        padding_left=pad_l,
        padding_right=pad_r,
        padding_top=pad_t,
        padding_bottom=pad_b,
        border_spacing_normal=sp_norm,
        border_spacing_compact=sp_comp,
        border_radius=radius,
        cell_padding_normal=cell_norm,
        cell_padding_compact=cell_comp,
    )

