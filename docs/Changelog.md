# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/); versions follow SemVer.

## [0.8.0] — 2026-08-24
### Added
- **File → New List** menu item: clears all MACs from the list and config, shows confirmation dialog.
- **Empty-state persistent label**: when no MACs are loaded, shows "No MAC addresses loaded yet" with instructions (File → Import, + Add MAC, Discover).
- **Discover devices button**: opens checkbox selection dialog; ARP sweep + DHCP cache scan populates discovered MACs.
- **Discover engine helpers**: `discover_hostnames()`, `discover_devices_v2()`, `scan_dhcp_cache()`, `probe_arp_cache()` in rotation_engine.py.
- **DHCP sniffer toggle in Settings menu**: start/stop/restart DHCP hostname sniffer from the menu bar.
- **Configurable auto-resolve interval**: 15s / 30s / 60s / 120s options in Settings menu, persisted to config.
- **Version single source**: `__version__` constant in rotation_engine.py; About dialog reads from it.
- **Persist original hostname**: saved on first MAC change for reliable restore.

### Changed
- **Import preserves metadata**: `load_mac_list()` returns dicts with `mac`, `hostname`, `firewall_allow` keys. Plain strings and RegisteredAddresses.json objects both handled.
- **Import deduplication**: duplicate MACs skipped with count in log summary.
- **Export handles dict input**: `export_mac_list()` accepts dicts or plain strings.
- **GUI wired to new features**: Discover button in MAC list frame, DHCP toggle in menu bar, auto-resolve interval in Settings.
- **Test suite**: VPN connectivity test updated for current dhcp_renew; wired into test_import.sh as step 7. Root-owned RegisteredAddresses.json tests skip gracefully.

### Fixed
- **Stale loaded-macs summary**: updated after import, not just at startup.
- **Original hostname restore**: uses persisted hostname instead of current hostname (which may already be randomized).
- **Config folder path**: uses `APP_DIR` instead of hardcoded `/tmp`.

## [0.7.3] — 2026-08-23
### Changed
- **Combined hostname resolution + last-seen update**: `resolve_hostnames_live()` now returns `(hostnames, last_seen)` tuple. ARP cache MACs get a `last_seen_at` timestamp. `_apply_resolved` updates both hostname labels and last-seen labels.
- **Auto-resolution timer**: 60s periodic timer resolves hostnames from DHCP cache without manual clicks. Logs only when new hostnames found. Skips during active rotation. Stops on app close.
- **Reduced duplicate DHCP logging**: sniffer checks existing cache before logging — same MAC+hostname pair logged once, not on every DHCP packet.

### Fixed
- `scripts/anonymize_hostnames.py` and `tests/test_vpn_connectivity.py` updated for new `resolve_hostnames_live()` tuple return type.

## [0.7.2] — 2026-08-23
### Added
- **DHCP hostname sniffer**: passive scapy-based thread listens for DHCP option-12 hostnames on all active interfaces. Captured hostnames persisted to `~/.config/mac-changer/dhcp_hostnames.json`. Integrated into `resolve_hostnames_live()` as fallback: ARP → reverse-DNS → gethostbyaddr → DHCP cache → register.
- `dhcp_hostnames_path()`, `load_dhcp_hostnames()`, `save_dhcp_hostnames()` engine helpers.
- `start_dhcp_sniffer(interfaces, log_cb)` — daemon thread, graceful PermissionError handling (exits silently when not root).

### Changed
- `resolve_hostnames_live()` now accepts `dhcp_hostnames` parameter; DHCP cache checked before register fallback.
- `default_config()` includes `dhcp_hostnames_enabled: True`.

## [0.7.1] — 2026-08-23
### Fixed
- **DNS resolution for on-link IPs**: `_ptr_via_router` now tries system DNS (resolv.conf) and `getent hosts` as fallbacks when router dig fails. Previously returned empty for on-link IPs (no `via` gateway). Also filters dig error output from results.
- **Row movement**: `_move_selected` now checks all row widgets (entry, check, hostname_lbl, last_lbl, fw_chk, remove_btn) for focus, not just entry and check.

## [0.7.0] — 2026-08-23
### Added
- **Window size persistence**: window geometry saved to `~/.config/mac-changer/config.json` on close, restored on next launch.
- **Drag-to-resize column headers**: drag handle between columns to resize; widths persisted in config.
- **File-based logging**: weekly rotation to `logs/mac-changer.log`, 4-week retention, timestamps on every entry.

### Fixed
- **DNS resolution in sudo/pkexec context**: `resolve_hostnames_live` now tries `_ptr_via_router` (uses `dig` via router DNS) before falling back to `socket.gethostbyaddr` (NSS, fails under systemd-resolved).

### Changed
- **Resizable MAC list frame**: frame expands to fill available window space (was fixed 180px height).

## [0.6.1] — 2026-08-23
### Fixed
- **Resolve hostnames now checks ARP cache for all MACs**: `resolve_hostnames_live` previously skipped ARP + reverse-DNS for MACs that already had hostnames in the register, reporting "No new hostnames resolved" even when devices were online. Now always checks the kernel neighbor table for every MAC; live-resolved hostnames override register values, falling back to register hostnames only for offline devices.

## [0.6.0] — 2026-08-18
### Added
- **Native menu bar**: File / Edit / View / Settings / Help menus with keyboard shortcuts (`Ctrl+I`, `Ctrl+E`, `Ctrl+S`, `Ctrl+A`, `Ctrl+Q`, `Ctrl+↑/↓`, `Ctrl+Shift+A/N`, `Del`, `Ctrl+F`).
- **Move up / Move down**: reorder MACs in the list via Edit menu or `Ctrl+↑`/`Ctrl+↓`.
- **Delete selected**: remove all checked (enabled) rows via Edit menu or `Del` key.
- **About dialog**: version and project link (Help → About).
- **Open config folder**: opens `~/.config/mac-changer/` in system file manager (Help → Open config folder).
- **Settings → Interface**: native submenu listing available interfaces.
- **View → Sort by**: submenu for sort columns (MAC, Hostname, Last seen, FW).

### Changed
- **Toolbar slimmed**: removed Import, Export, Save list, Scan registered, Select all, Select none, Clear list buttons from toolbar — accessible via menus only. Toolbar now has: + Add MAC, Filter, Start/Stop, Restore.
- Window min height bumped from 520 → 550 to accommodate menu bar.

## [0.5.0] — 2026-08-18
### Added
- **Hostname rotation**: optional system hostname change alongside MAC address rotation. Configurable pattern with `{mac}`, `{mac_suffix}`, `{mac_hex}` placeholders. mDNS restart after change. Original hostname stored for restore.
- **GUI controls**: "Rotate hostname" checkbox and pattern text entry in the interval settings row. Pattern defaults to `device-{mac_suffix}`.
- **Config persistence**: `hostname_enabled` and `hostname_pattern` saved to `~/.config/mac-changer/config.json`.
- **Restore integration**: Restore button reverts both MAC and hostname to original values.

## [0.4.2] — 2026-08-18
### Fixed
- **DHCP renewal after MAC change**: `dhcp_renew()` rewritten to use `nmcli connection down/up` as primary method — fully tears down and re-establishes the connection with a fresh DHCP request, which is reliable after a MAC swap (the old lease is bound to the previous hardware address). Falls back to `nmcli device reapply` (minor changes), then `dhclient` if available. Added `_get_nm_connection_name(iface)` helper to resolve the NM connection name for an interface.
### Added
- **Loaded-MAC list display**: `get_loaded_macs(cfg)` returns the in-memory MAC list as `[{mac, enabled}]`; `loaded_macs_summary(cfg)` returns a human-readable count (e.g. `"8 MACs loaded (2 enabled, 6 disabled)"`). GUI top-bar label shows the count on every update. Rotation start log lists each enabled MAC individually. Config population, import, and save log the updated count.
### Changed
- `docs/Context.md` updated: `dhcp_renew` description reflects the new `nmcli connection down/up` strategy; runtime environment notes updated to remove `dhclient` as required.

## [0.4.1] — 2026-08-16
### Added
- **Firewall allow field**: `RegisteredAddresses.json` entries now carry `firewall_allow: bool` (default `true`); all existing entries backfilled (order/other fields preserved). `load_registered`, the new `firewall_map` engine helper, and `scripts/extract_macs.py` emit/preserve the field.
- **Live per-MAC firewall detection**: `detect_firewall_allow(iface)` in `src/rotation_engine.py` classifies the existing connectivity gate (ok ⇒ `true`; gateway-up + internet probe blocked ⇒ `false`; no IPv4 / gateway down / probe unavailable ⇒ `None`). `RotationWorker` records non-`None` results after each rotation via the new atomic `set_firewall_allow(mac, allowed)` single-field update.
- **Bool-aware merge**: `merge_register` now preserves `firewall_allow: false` when the row carries the key (previously truthy-only fields would drop it); inserted entries default `true`.
- **GUI FW checkbox**: each MAC row gains a "FW" checkbox (column 4, ✕ moves to column 5) seeded from the register, persisted on Save list, refreshed when a row's MAC is edited.
- `tests/test_firewall_allow.py` (classification, map defaults/coercion, bool-aware merge, atomic single-field set, real-register backfill shape) wired as step 6 of `tests/test_import.sh`; `test_list_io`/`test_anonymize_hostnames` extended to assert the field.

## [0.4.0] — 2026-08-16
### Added
- **Hostname anonymization**: `scripts/anonymize_hostnames.py` replaces every non-RFC hostname in `RegisteredAddresses.json` with a unique, deterministic dictionary word derived from the device MAC (hash → word index, collision-skipped, never collides with kept valid hostnames). Deterministic across re-runs; `--dry-run` by default writes nothing; real runs are atomic (temp + rename) with a `.bak` backup.
- **`scan` mode**: live-resolves real hostnames (ARP cache + reverse-DNS via the engine) and inserts them over dictionary-word placeholders only — valid/real hostnames are never overwritten.
- **Engine helpers** `is_valid_hostname(name)` (RFC 1123/952 check) and `blank_hostnames(devices, wordlist)` in `src/rotation_engine.py` — pure, reusable from the GUI later.
- Embedded ~340-word English wordlist (`--wordlist PATH` to override).
- `tests/test_anonymize_hostnames.py` (classification, determinism, uniqueness, no-loss round-trip, placeholder-only scan with mocked resolver, atomic-write backup) wired into `tests/test_import.sh`.

## [0.3.0] — 2026-08-05
### Added
- MAC list enrichment: every row now shows the device's **hostname** and **last-seen** timestamp beside the MAC (filled from `RegisteredAddresses.json` + `data/last_seen.json`; auto-refreshes as you type).
- **Sort by MAC** / **Sort by hostname** buttons reorder the list case-insensitively without losing the enabled state.
- **Select all** / **Select none** tick/untick every row's checkbox.
- **Filter box** hides non-matching rows by MAC or hostname substring — display-only, so hidden rows still rotate.
- **Resolve hostnames** button: register map first, then live ARP-cache + reverse-DNS (`socket.gethostbyaddr`, short timeout) for unknown MACs, run in a background thread with `after(0, ...)` UI updates; resolved names persist to config.
- **Save list** merges the current rows back into `RegisteredAddresses.json` (update matching MACs, insert new ones, never shrink the register; missing register is recreated). Writes atomically.
- Import/export dialogs now remember their last directory (`last_import_dir`/`last_export_dir` config keys) and seed the next picker from it.
- Config `macs` entries grow to `{"mac", "enabled", "hostname", "last_seen_at"}` (all optional, fully backward compatible).
- `tests/test_list_enrichment.py` (hostname_map, merge update/insert/never-shrink, last_seen_for, enriched config round-trip, live-resolve fallback) and `tests/smoke_070.py` (row labels, select all/none, sort preserves enabled, display-only filter) — wired into `tests/test_import.sh`.

## [0.2.2] — 2026-08-05
### Added
- Interface down-delay setting: a selectable hold time (Off/1s/2s/3s/5s/10s/15s/30s) between link-down and link-up during MAC rotation, so the network fully releases the old MAC before reconnecting. Implemented project-locally in `src/rotation_engine.py` (`change_mac_delayed()`, `down_delay_seconds` config key, `RotationWorker.down_delay` param); fisheye-gui `lib/mac_tools.py` stays unmodified. Default `0` preserves the previous immediate behavior.
- `tests/smoke_069.py` — no-root smoke suite covering the delayed down/up sequence, delay-0 byte-equivalence, interruptible sleep, down-failure short-circuit, config round-trip + int coercion, worker param wiring, scroll guard, and GUI selector construction (all groups pass).
### Fixed
- Scrolling the MAC list no longer crashes the app. customtkinter 6.0.0's `_check_if_valid_scroll` raises `AttributeError: 'str' object has no attribute 'master'` when a mouse-wheel event carries a Tcl pathname string (e.g. mid-row-destroy). Fixed with a project-local `SafeScrollableFrame` subclass that guards string/`None` widgets (no venv patch).

## [0.2.1] — 2026-08-01
### Changed
- Registered-device field renamed `last_working_at` → `last_seen_at` (was a `"test"` placeholder); the extractor now leaves it empty.
### Added
- Last-seen detection: `scan_registered` / `probe_mac_seen` in `src/rotation_engine.py` read the kernel neighbor table (`ip neigh`) via `mac_tools.check_arp_cache` (single table read, optional active ping confirmation), stamping real observation timestamps.
- "Scan registered" GUI button runs the scan in a background thread and logs which registered devices are currently on the network.
- Observed state persists separately to `data/last_seen.json` (`{mac: ISO timestamp}`, gitignored) so re-running `extract_macs.py` never clobbers it; timestamps are never regressed.
- `load_registered` engine helper parses `RegisteredAddresses.json` → `[{mac, hostname}]`.

## [0.2.0] — 2026-08-01
### Added
- MAC list import/export: "Import list" / "Export list" buttons in the GUI using the native
  `customtkinter.filedialog` pickers.
- `src/rotation_engine.py` list helpers: `load_mac_list` (tolerant JSON reader — plain string
  arrays or object arrays with a `mac` key; normalizes, dedupes, skips invalid) and
  `export_mac_list` (writes a normalized/deduped JSON array; round-trips with the loader).
- `RegisteredAddresses.json` — registered devices extracted from a tab-separated device export
  (`{"mac", "hostname", "last_working_at"}` sorted by hostname).
- `scripts/extract_macs.py` — reusable register parser: reads any tab-separated device export
  (`devices*.txt`), locates MAC cells by regex, dedupes, writes `RegisteredAddresses.json`;
  runnable for future exports (`--last-working-at` overrides the timestamp field).
- `tests/test_list_io.py` — round-trip, normalization, dedupe, invalid-entry, and register-count
  tests; wired into `tests/test_import.sh`.

## [0.1.1] — 2026-08-01
### Fixed
- `gui.sh` relaunch used `bash "$0"` — `pkexec` resets the working directory, so `./gui.sh` could not be found after elevation ("No such file or directory"). Now relaunches via absolute path `bash "$DIR/gui.sh"`.
### Added
- Root GUI smoke verified on desktop (`./gui.sh --smoke` PASS).

## [0.1.0] — 2026-08-01
### Added
- Standalone project scaffolded per `~/Project_template.md` (src/, docs/, tests/, scripts/, logs/).
- `src/rotation_engine.py`:
  - GUI-independent core: `RotationWorker` thread (backup original → `mac_tools.change_mac` → `dhcp_renew` → `test_connection`; on failure advance immediately to next enabled MAC).
  - Local helpers: `get_interface_ip`, `get_gateway`, `dhcp_renew`, `test_connection`.
  - JSON config persistence at `~/.config/mac-changer/config.json`.
- `src/mac_changer.py`: CustomTkinter GUI (interface dropdown, current-MAC label, MAC list editor with per-row enable checkboxes, interval selector, Start/Stop toggle, log pane, Restore original button); imports `rotation_engine`.
- `gui.sh`: root launcher (euid assert, `.venv` bootstrap, dep install, pkexec/sudo with DISPLAY/XAUTHORITY forwarding).
- Reuses fisheye-gui `lib/mac_tools.py` via `sys.path` (unmodified).
- Docs set per template; spec folder `066-mac-changer` validated (`validate.sh --strict` PASS).
