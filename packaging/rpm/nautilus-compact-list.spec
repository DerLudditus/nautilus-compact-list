%{!?pkg_version: %define pkg_version 0.1.0}
%{!?pkg_release: %define pkg_release 20}

Name:           nautilus-compact-list
Version:        %{pkg_version}
Release:        %{pkg_release}
Summary:        Classic Nautilus-style Compact List view with variable-width columns for GNOME Files

License:        MIT
URL:            https://github.com/DerLudditus/nautilus-compact-list
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  make
BuildRequires:  python3
BuildRequires:  glib2-devel

Requires:       nautilus-python
Requires:       gtk4
Requires:       libadwaita

%description
Brings back the classic multi-column Compact List view (present in GNOME 2
Nautilus, Caja, Thunar, Dolphin, PCManFM/PCManFM-Qt) to modern GNOME Files
(GTK4 Nautilus) with variable-width columns, smart filename shortening, and
status bar.

%prep
%autosetup

%build
# Pure python / schema extension

%install
mkdir -p %{buildroot}%{_datadir}/nautilus-python/extensions
mkdir -p %{buildroot}%{_datadir}/glib-2.0/schemas
cp -p nautilus-compact-list.py version.py %{buildroot}%{_datadir}/nautilus-python/extensions/
cp -pr nautilus_compact_list %{buildroot}%{_datadir}/nautilus-python/extensions/
find %{buildroot}%{_datadir}/nautilus-python/extensions/nautilus_compact_list -name "__pycache__" -type d -exec rm -rf {} +
find %{buildroot}%{_datadir}/nautilus-python/extensions/nautilus_compact_list -name "*.pyc" -delete
cp -p io.github.nautilus-compact-list.gschema.xml %{buildroot}%{_datadir}/glib-2.0/schemas/

%files
%license LICENSE
%doc README.md
%{_datadir}/nautilus-python/extensions/nautilus-compact-list.py
%{_datadir}/nautilus-python/extensions/version.py
%{_datadir}/nautilus-python/extensions/nautilus_compact_list/
%{_datadir}/glib-2.0/schemas/io.github.nautilus-compact-list.gschema.xml

%changelog
* Thu Nov 05 2026 Homo Ludditus <DerLudditus@gmail.com> - 0.1.0-20
- In-tree multi-language localization catalog for custom UI strings across major languages

