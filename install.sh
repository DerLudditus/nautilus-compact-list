#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-${HOME}/.local}"
EXT_DIR="${EXT_DIR:-${PREFIX}/share/nautilus-python/extensions}"
SCHEMA_DIR="${SCHEMA_DIR:-${PREFIX}/share/glib-2.0/schemas}"
SCHEMA_FILE="io.github.nautilus-compact-list.gschema.xml"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -rf "${EXT_DIR}/nautilus-compact-list.py" "${EXT_DIR}/version.py" "${EXT_DIR}/nautilus_compact_list"
    rm -f "${SCHEMA_DIR}/${SCHEMA_FILE}"
    if command -v glib-compile-schemas >/dev/null 2>&1 && [[ -d "${SCHEMA_DIR}" ]]; then
        glib-compile-schemas "${SCHEMA_DIR}" || true
    fi
    echo "Uninstalled nautilus-compact-list."
    if command -v nautilus >/dev/null 2>&1; then
        nautilus -q || true
    fi
    exit 0
fi

mkdir -p "${EXT_DIR}" "${SCHEMA_DIR}"
cp -f nautilus-compact-list.py version.py "${EXT_DIR}/"
rm -rf "${EXT_DIR}/nautilus_compact_list"
cp -r nautilus_compact_list "${EXT_DIR}/"
cp -f "${SCHEMA_FILE}" "${SCHEMA_DIR}/"

if command -v glib-compile-schemas >/dev/null 2>&1; then
    glib-compile-schemas "${SCHEMA_DIR}"
fi

echo "Installed nautilus-compact-list to ${EXT_DIR}."
echo "Run 'nautilus -q && nautilus' to reload Nautilus."
