"""
Nautilus Compact List - Version Information

This is the single source of truth for version information.
Update this file when releasing a new version.
"""

__version__ = "0.1.0"
__version_info__ = (0, 1, 0)

# Release information
RELEASE_DATE = "2026-11-04"
RELEASE_NAME = "Nautilus Compact List"

# Package information for .deb and .rpm
DEB_VERSION = "0.1.0-20"
DEB_MAINTAINER = "Homo Ludditus <DerLudditus@gmail.com>"
DEB_HOMEPAGE = "https://github.com/DerLudditus/nautilus-compact-list"

# Changelog entry (most recent first)
CHANGELOG = """nautilus-compact-list (0.1.0-20) trixie; urgency=medium

  * In-tree multi-language localization catalog for custom UI strings:
    - Add native, concise menu translations across major languages in nautilus_compact_list/i18n.py
      for "Set Max Column Width…", "Max chars:", and "Apply". Zero .mo overhead.

 -- Homo Ludditus <DerLudditus@gmail.com>  Thu, 05 Nov 2026 21:30:00 +0200
