#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Read metadata from single source of truth (version.py)
if [[ -f version.py ]]; then
    VERSION="$(python3 -c 'import version; print(version.DEB_VERSION)')"
    MAINTAINER="$(python3 -c 'import version; print(version.DEB_MAINTAINER)')"
    HOMEPAGE="$(python3 -c 'import version; print(version.DEB_HOMEPAGE)')"
    # Auto-sync debian/changelog from version.py
    mkdir -p debian
    python3 -c 'import version; print(version.CHANGELOG.strip())' > debian/changelog
else
    VERSION="$(dpkg-parsechangelog -SVersion 2>/dev/null || grep -m1 -oP '^[^(]+\(\K[^)]+' debian/changelog 2>/dev/null || echo "0.1.0-8")"
    MAINTAINER="Homo Ludditus <DerLudditus@gmail.com>"
    HOMEPAGE="https://github.com/DerLudditus/nautilus-compact-list"
fi

PKG_NAME="nautilus-compact-list"
DIST_DIR="$SCRIPT_DIR/dist"
OUTPUT_DEB="$DIST_DIR/${PKG_NAME}_${VERSION}_all.deb"
MODE="dpkg-deb"

for arg in "$@"; do
    case "$arg" in
        --dpkg-buildpackage|--source|-s)
            MODE="dpkg-buildpackage"
            ;;
        --clean|-c)
            rm -rf "$DIST_DIR" debian/.debhelper debian/nautilus-compact-list debian/files debian/*.substvars debian/*.debhelper.log
            echo "Cleaned build artifacts and dist/."
            exit 0
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  (default)                Build .deb directly using dpkg-deb (fast, self-contained)"
            echo "  --dpkg-buildpackage, -s  Build using canonical dpkg-buildpackage / debhelper"
            echo "  --clean, -c              Clean build artifacts and dist/"
            echo "  --help, -h               Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Run '$0 --help' for usage." >&2
            exit 1
            ;;
    esac
done

mkdir -p "$DIST_DIR"

if [[ "$MODE" == "dpkg-buildpackage" ]]; then
    echo "=== Building via dpkg-buildpackage ==="
    if ! command -v dpkg-buildpackage >/dev/null 2>&1; then
        echo "Error: dpkg-buildpackage is not installed." >&2
        exit 1
    fi
    dpkg-buildpackage -us -uc -b
    # Move output deb from parent directory to dist/
    PARENT_DIR="$(dirname "$SCRIPT_DIR")"
    if compgen -G "$PARENT_DIR/${PKG_NAME}_${VERSION}_*.deb" > /dev/null; then
        mv "$PARENT_DIR"/${PKG_NAME}_${VERSION}_*.deb "$DIST_DIR/"
        mv "$PARENT_DIR"/${PKG_NAME}_${VERSION}_*.buildinfo "$DIST_DIR/" 2>/dev/null || true
        mv "$PARENT_DIR"/${PKG_NAME}_${VERSION}_*.changes "$DIST_DIR/" 2>/dev/null || true
    fi
else
    echo "=== Building via dpkg-deb ==="
    if ! command -v dpkg-deb >/dev/null 2>&1; then
        echo "Error: dpkg-deb is not installed." >&2
        exit 1
    fi

    STAGE_DIR="$(mktemp -d)"
    trap 'rm -rf "$STAGE_DIR"' EXIT

    EXT_DEST="$STAGE_DIR/usr/share/nautilus-python/extensions"
    SCHEMA_DEST="$STAGE_DIR/usr/share/glib-2.0/schemas"
    DOC_DEST="$STAGE_DIR/usr/share/doc/$PKG_NAME"
    DEBIAN_DEST="$STAGE_DIR/DEBIAN"

    mkdir -p "$EXT_DEST" "$SCHEMA_DEST" "$DOC_DEST" "$DEBIAN_DEST"

    # 1. Install extension files
    cp -p nautilus-compact-list.py version.py "$EXT_DEST/"
    cp -pr nautilus_compact_list "$EXT_DEST/"
    find "$EXT_DEST/nautilus_compact_list" -name "__pycache__" -type d -exec rm -rf {} +
    find "$EXT_DEST/nautilus_compact_list" -name "*.pyc" -delete

    # 2. Install GSettings schema
    cp -p io.github.nautilus-compact-list.gschema.xml "$SCHEMA_DEST/"

    # 3. Documentation
    cp -p LICENSE "$DOC_DEST/copyright"
    cp -p README.md "$DOC_DEST/"
    if [[ -f debian/changelog ]]; then
        gzip -c9 debian/changelog > "$DOC_DEST/changelog.Debian.gz"
    fi

    # 4. Control file
    cat <<EOF > "$DEBIAN_DEST/control"
Package: $PKG_NAME
Version: $VERSION
Section: gnome
Priority: optional
Architecture: all
Maintainer: $MAINTAINER
Homepage: $HOMEPAGE
Depends: python3-nautilus, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1
Description: Classic Nautilus-style Compact List view for GNOME Files
 Brings back the classic multi-column Compact List view (present in GNOME 2
 Nautilus, Caja, Thunar, Dolphin, PCManFM/PCManFM-Qt) to modern GNOME Files
 (GTK4 Nautilus) with variable-width columns, smart filename shortening, and
 status bar.
EOF

    # 5. Maintainer scripts for GSettings schema compilation
    cat <<'EOF' > "$DEBIAN_DEST/postinst"
#!/bin/sh
set -e
if [ "$1" = "configure" ] && command -v glib-compile-schemas >/dev/null 2>&1; then
    glib-compile-schemas /usr/share/glib-2.0/schemas || true
fi
exit 0
EOF

    cat <<'EOF' > "$DEBIAN_DEST/postrm"
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v glib-compile-schemas >/dev/null 2>&1 && [ -d /usr/share/glib-2.0/schemas ]; then
        glib-compile-schemas /usr/share/glib-2.0/schemas || true
    fi
fi
exit 0
EOF

    chmod 0755 "$STAGE_DIR" "$DEBIAN_DEST"
    chmod 0755 "$DEBIAN_DEST/postinst" "$DEBIAN_DEST/postrm"
    chmod -R u=rwX,go=rX "$STAGE_DIR/usr"
    chmod 0644 "$DEBIAN_DEST/control"

    dpkg-deb --build --root-owner-group "$STAGE_DIR" "$OUTPUT_DEB"
fi

echo ""
echo "=== Build Succeeded ==="
echo "Package built at: $OUTPUT_DEB"
echo ""
echo "Package info:"
dpkg-deb -I "$OUTPUT_DEB"
echo ""
echo "Contents:"
dpkg-deb -c "$OUTPUT_DEB"
echo ""
echo "To install on your Debian 13 system, run:"
echo "  sudo apt install $OUTPUT_DEB"
echo "  nautilus -q && nautilus"
