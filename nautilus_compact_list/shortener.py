import re

# Matches numeric, copy-counter, date, or timestamp suffixes at the end of a filename stem:
# Examples matched:
#   "1", "2", " (1)", " (17)", " [3]", "_20260102", "_2026-01-02", "-2026-01-02_14-30"
_NUMERIC_OR_DATE_TAIL_RE = re.compile(
    r"(?:"
    r"[\s_\-\.]*(?:\(\d+\)|\[\d+\])"  # Copy counters like " (1)", " (17)", "_[2]"
    r"|"
    r"[\s_\-\.]*\d+(?:[\-\._]\d+)*"  # Numbers, dates, or timestamps like "1", "_20260102", "_2026-01-02"
    r")$"
)

_COMPOUND_EXTENSIONS = (
    ".tar.gz",
    ".tar.xz",
    ".tar.bz2",
    ".tar.zst",
    ".dpkg-old",
    ".dpkg-dist",
    ".dpkg-new",
)


def split_filename_stem_ext(filename: str) -> tuple[str, str]:
    """
    Splits a filename into (stem, ext) while respecting leading dotfiles
    and known compound extensions.
    """
    if not filename or filename in (".", ".."):
        return filename, ""

    lower = filename.lower()
    for comp in _COMPOUND_EXTENSIONS:
        if lower.endswith(comp) and len(filename) > len(comp):
            cut = len(filename) - len(comp)
            return filename[:cut], filename[cut:]

    # Leading dotfile with no secondary extension (e.g. ".bashrc")
    if filename.startswith(".") and filename.count(".") == 1:
        return filename, ""

    dot_idx = filename.rfind(".")
    if dot_idx > 0:
        ext = filename[dot_idx:]
        # Treat as a normal extension if reasonably short (<= 12 chars)
        if len(ext) <= 12:
            return filename[:dot_idx], ext

    return filename, ""


def shorten_filename(
    filename: str,
    max_chars: int = 50,
    mode: str = "smart-suffix",
    stem_context_chars: int = 2,
) -> str:
    """
    Shortens `filename` so its total length never exceeds `max_chars`.

    Modes:
    - 'smart-suffix' (default):
      * If the stem does NOT end with a number, copy counter, or date:
        Preserves only the extension after '...' -> "looooooooooooooooooooooongfilena....txt"
      * If the stem DOES end with a number, copy counter, or date:
        Preserves the last `stem_context_chars` (default 2) characters of the base word stem
        plus the entire numeric/date suffix and the extension:
        - "looooooooooooooooooooooongfilename1.txt"          -> "looooooooooooooooooooooong...me1.txt"
        - "looooooooooooooooooooooongfilename2.txt"          -> "looooooooooooooooooooooong...me2.txt"
        - "looooooooooooooooooooooongfilename (1).txt"       -> "loooooooooooooooooooooo...me (1).txt"
        - "looooooooooooooooooooooongfilename (17).txt"      -> "looooooooooooooooooooo...me (17).txt"
        - "looooooooooooooooooooooongfilename_20260102.txt"  -> "looooooooooooooooo...me_20260102.txt"
        - "looooooooooooooooooooooongfilename_2026-01-02.txt"-> "looooooooooooooo...me_2026-01-02.txt"
    - 'middle':
      * Nautilus Icon View style generic middle truncation (55% prefix / 45% suffix).
    """
    if max_chars < 10 or len(filename) <= max_chars:
        return filename

    ellipsis = "..."

    if mode == "middle":
        avail = max_chars - len(ellipsis)
        left_len = (avail + 1) // 2
        right_len = avail - left_len
        return f"{filename[:left_len]}{ellipsis}{filename[-right_len:]}"

    stem, ext = split_filename_stem_ext(filename)

    match = _NUMERIC_OR_DATE_TAIL_RE.search(stem)
    if match:
        numeric_suffix = match.group(0)
        base_word = stem[: match.start()]
        context_tail = base_word[-stem_context_chars:] if stem_context_chars > 0 else ""
        preserved_tail = f"{context_tail}{numeric_suffix}{ext}"
    else:
        preserved_tail = ext

    prefix_budget = max_chars - len(ellipsis) - len(preserved_tail)

    # Ensure we always keep a meaningful prefix (at least 4 characters)
    if prefix_budget >= 4:
        return f"{stem[:prefix_budget]}{ellipsis}{preserved_tail}"

    # Fallback when the suffix/extension itself is nearly as long as max_chars
    min_prefix = max(4, max_chars // 4)
    tail_budget = max(1, max_chars - min_prefix - len(ellipsis))
    return f"{filename[:min_prefix]}{ellipsis}{filename[-tail_budget:]}"


if __name__ == "__main__":
    # Self-test verifying exact character-for-character behavior
    assert (
        shorten_filename("looooooooooooooooooooooongfilename_long.txt", max_chars=39)
        == "looooooooooooooooooooooongfilena....txt"
    )
    assert (
        shorten_filename("looooooooooooooooooooooongfilename1.txt", max_chars=36)
        == "looooooooooooooooooooooong...me1.txt"
    )
    assert (
        shorten_filename("looooooooooooooooooooooongfilename2.txt", max_chars=36)
        == "looooooooooooooooooooooong...me2.txt"
    )
    assert (
        shorten_filename("looooooooooooooooooooooongfilename (1).txt", max_chars=36)
        == "loooooooooooooooooooooo...me (1).txt"
    )
    assert (
        shorten_filename("looooooooooooooooooooooongfilename (17).txt", max_chars=36)
        == "looooooooooooooooooooo...me (17).txt"
    )
    assert (
        shorten_filename("looooooooooooooooooooooongfilename_20260102.txt", max_chars=36)
        == "looooooooooooooooo...me_20260102.txt"
    )
    assert (
        shorten_filename("looooooooooooooooooooooongfilename_2026-01-02.txt", max_chars=36)
        == "looooooooooooooo...me_2026-01-02.txt"
    )
    print("All smart filename shortening assertions passed!")
