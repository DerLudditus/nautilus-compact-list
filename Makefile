PREFIX ?= $(HOME)/.local
EXT_DIR ?= $(PREFIX)/share/nautilus-python/extensions
SCHEMA_DIR ?= $(PREFIX)/share/glib-2.0/schemas

.PHONY: all install uninstall restart lint format test deb rpm

all:
	@echo "Targets: install, uninstall, restart, lint, format, test, deb, rpm"

deb:
	./build-deb.sh

rpm:
	./build-rpm.sh

install:
	./install.sh

uninstall:
	./install.sh --uninstall

restart:
	-nautilus -q
	nohup nautilus >/dev/null 2>&1 &

lint:
	python3 -m py_compile nautilus-compact-list.py version.py nautilus_compact_list/*.py
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check nautilus-compact-list.py version.py nautilus_compact_list/; \
	fi

format:
	@if command -v ruff >/dev/null 2>&1; then \
		ruff format nautilus-compact-list.py version.py nautilus_compact_list/; \
	else \
		echo "ruff not found, skipping format"; \
	fi

test:
	python3 -m nautilus_compact_list.shortener
