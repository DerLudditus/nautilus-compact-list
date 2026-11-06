#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Read metadata from single source of truth (version.py)
if [[ -f version.py ]]; then
    VERSION="$(python3 -c 'import version; print(version.__version__)')"
    DEB_VER="$(python3 -c 'import version; print(version.DEB_VERSION)')"
    if [[ "$DEB_VER" == *"-"* ]]; then
        RELEASE="${DEB_VER##*-}"
    else
        RELEASE="1"
    fi
else
    VERSION="0.1.0"
    RELEASE="8"
fi

PKG_NAME="nautilus-compact-list"
DIST_DIR="$SCRIPT_DIR/dist"
SPEC_FILE="$SCRIPT_DIR/packaging/rpm/nautilus-compact-list.spec"

for arg in "$@"; do
    case "$arg" in
        --clean|-c)
            rm -rf "$SCRIPT_DIR/rpmbuild" "$DIST_DIR"/*.rpm
            echo "Cleaned RPM build tree and dist/*.rpm."
            exit 0
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  (default)   Build .rpm using rpmbuild"
            echo "  --clean, -c Clean rpmbuild/ and dist/*.rpm"
            echo "  --help, -h  Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Run '$0 --help' for usage." >&2
            exit 1
            ;;
    esac
done

if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "Error: rpmbuild is not installed." >&2
    echo "Install rpm-build / rpmdevtools on Fedora: sudo dnf install -y rpm-build rpmdevtools" >&2
    echo "Install rpm on Debian/Ubuntu: sudo apt-get install -y rpm" >&2
    exit 1
fi

mkdir -p "$DIST_DIR"
RPM_TOPDIR="$SCRIPT_DIR/rpmbuild"
mkdir -p "$RPM_TOPDIR/SOURCES" "$RPM_TOPDIR/SPECS" "$RPM_TOPDIR/BUILD" "$RPM_TOPDIR/RPMS" "$RPM_TOPDIR/SRPMS"

# 1. Create clean source tarball
TAR_NAME="${PKG_NAME}-${VERSION}.tar.gz"
TEMP_SRC="$(mktemp -d)"
trap 'rm -rf "$TEMP_SRC"' EXIT

SRC_DIR="$TEMP_SRC/${PKG_NAME}-${VERSION}"
mkdir -p "$SRC_DIR"

cp -p nautilus-compact-list.py version.py io.github.nautilus-compact-list.gschema.xml LICENSE README.md Makefile install.sh pyproject.toml "$SRC_DIR/"
cp -pr nautilus_compact_list "$SRC_DIR/"
find "$SRC_DIR" -name "__pycache__" -type d -exec rm -rf {} +
find "$SRC_DIR" -name "*.pyc" -delete

tar -czf "$RPM_TOPDIR/SOURCES/$TAR_NAME" -C "$TEMP_SRC" "${PKG_NAME}-${VERSION}"

# 2. Copy spec file
cp -p "$SPEC_FILE" "$RPM_TOPDIR/SPECS/"

# 3. Build RPM with dynamic version and release defines
rpmbuild --nodeps \
         --define "_topdir $RPM_TOPDIR" \
         --define "_tmppath /tmp" \
         --define "_dbpath $RPM_TOPDIR/rpmdb" \
         --define "pkg_version $VERSION" \
         --define "pkg_release $RELEASE" \
         --define "dist %{nil}" \
         -bb "$RPM_TOPDIR/SPECS/$(basename "$SPEC_FILE")"

# 4. Copy resulting RPM to dist/
cp -f "$RPM_TOPDIR"/RPMS/*/*.rpm "$DIST_DIR/"

echo ""
echo "=== RPM Build Succeeded ==="
find "$DIST_DIR" -name "*.rpm" -exec echo "Package built at: {}" \;
echo ""
echo "To install on Fedora, run:"
echo "  sudo dnf install ./dist/*.noarch.rpm"
echo "  nautilus -q && nautilus"
