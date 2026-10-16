# Code Change Log

Audit trail of substantive code changes. Most recent first.

## 2026-08-23 — Auto-resolution + combined last-seen (v0.7.3)
### Changed
- `src/rotation_engine.py`:
  - `resolve_hostnames_live()`: return type changed from `dict` to `tuple[dict, dict]` — `(hostnames, last_seen)`. ARP cache MACs now get `last_seen_at` timestamp. `save_seen_state` caller responsibility.
  - `_handler()` in `start_dhcp_sniffer()`: checks existing cache before logging to reduce duplicates.
- `src/mac_changer.py`:
  - `_resolve_worker()`: unpacks `(names, last_seen)` tuple.
  - `_apply_resolved()`: now accepts `last_seen` dict; updates both hostname labels and last-seen labels; persists last-seen via `save_seen_state`.
  - `_start_auto_resolve()`, `_auto_resolve_tick()`, `_auto_resolve_worker()`: 60s periodic timer resolves hostnames from DHCP cache. Skips during rotation. Stops on close.
  - `on_close()`: cancels auto-resolve timer.
  - Added `save_seen_state` to imports.
- `scripts/anonymize_hostnames.py`: updated for tuple return type.
- `tests/test_list_enrichment.py`: updated for tuple return type; added last_seen assertion.
- `tests/test_vpn_connectivity.py`: updated for tuple return type.

## 2026-08-23 — DHCP hostname sniffer (v0.7.2)
### Changed
- `src/rotation_engine.py`:
  - `dhcp_hostnames_path()`: new path helper for `~/.config/mac-changer/dhcp_hostnames.json`.
  - `load_dhcp_hostnames()`: loads `{mac: hostname}` from JSON, validates MACs.
  - `save_dhcp_hostnames(mac, hostname)`: atomic single-entry persist.
  - `start_dhcp_sniffer(interfaces, log_cb)`: daemon thread using scapy `sniff()` with BPF filter `udp and (port 67 or port 68)`. Parses BOOTP chaddr → MAC, DHCP option 12 → hostname. Graceful PermissionError handling.
  - `resolve_hostnames_live()`: new `dhcp_hostnames` parameter; resolution chain now ARP → reverse-DNS → gethostbyaddr → DHCP cache → register.
  - `default_config()`: added `dhcp_hostnames_enabled: True`.
- `src/mac_changer.py`:
  - Added `start_dhcp_sniffer` to imports.
  - `_active_interfaces()`: new helper returns non-loopback interfaces.
  - `__init__`: starts DHCP sniffer on all active interfaces (if enabled in config).
  - `_log_threadsafe`: catches RuntimeError for safe teardown.

## 2026-08-23 — DNS + row move fix (v0.7.1)
### Changed
- `src/rotation_engine.py`:
  - `_dig_reverse`: new helper; runs `dig -x <ip>` with optional server, filters error output (lines starting with `;`).
  - `_getent_host`: new helper; runs `getent hosts <ip>` for /etc/hosts + NSS lookup.
  - `_ptr_via_router`: now tries router dig, then system DNS (no `@`), then `getent hosts`. No longer returns empty when no `via` gateway found (on-link IPs).
- `src/mac_changer.py`:
  - `_move_selected`: checks all row widgets (`_row_widgets(r)`) for focus, not just `entry` and `check`.

## 2026-08-23 — GUI enhancements (v0.7.0)
### Changed
- `src/rotation_engine.py`:
  - `resolve_hostnames_live`: now tries `_ptr_via_router` first (uses `dig` via router DNS), then falls back to `socket.gethostbyaddr` (NSS). Fixes DNS failure in sudo/pkexec context.
  - `default_config`: added `window_geometry` and `column_widths` keys.
  - `setup_file_logger`: new function; configures weekly-rotating file logger at `logs/mac-changer.log`.
- `src/mac_changer.py`:
  - `MacChangerApp.__init__`: restores window geometry from config; initializes `_col_widths` and `_file_logger`.
  - `on_close`: saves window geometry and column widths to config.
  - `log`: writes to both GUI widget and file logger.
  - `_build_header_bar`: uses `_col_widths` for column widths; adds drag handles between columns for resizing.
  - `_col_resize_start` / `_col_resize_drag`: new methods for column drag-to-resize.
  - `_add_mac_row`: uses `_col_widths` for entry/label widths.
  - `mac_frame`: changed from fixed height=180 to `fill="both", expand=True`.
- `tests/test_list_enrichment.py`: mock `_ptr_via_router` in reverse-DNS test.
- `tests/smoke_100.py`: updated `BUTTON_TIPS`, `ATTR_TIPS` to match current widget set.

## 2026-08-23 — Resolve hostnames fix (v0.6.1)
### Changed
- `src/rotation_engine.py`:
  - `resolve_hostnames_live`: always checks ARP cache for all MACs; live-resolved hostnames override register values, falling back to register hostnames for offline devices. Previously skipped ARP + reverse-DNS for MACs with existing hostnames in the register.

## 2026-08-18 — Native menu bar + toolbar cleanup (v0.6.0)
### Added
- `src/mac_changer.py`:
  - `_build_menu()`: native `tk.Menu` bar with File (Import, Export, Save, Exit), Edit (Add, Move up/down, Select all/none, Delete selected, Clear), View (Sort by ▸, Resolve hostnames, Scan registered, Filter), Settings (Interface ▸), Help (About, Open config folder).
  - `_bind_shortcuts()`: keyboard shortcuts — `Ctrl+I/E/S/A/Q`, `Ctrl+↑/↓`, `Ctrl+Shift+A/N`, `Del`, `Ctrl+F`.
  - `_move_selected(direction)`: reorder MAC rows via focused row detection.
  - `_delete_selected()`: remove all checked (enabled) rows.
  - `_focus_filter()`: jump focus to filter text entry.
  - `_show_about()`: `tkinter.messagebox.showinfo` with version and project link.
  - `_open_config_folder()`: `xdg-open` on `~/.config/mac-changer/`.
  - `_refresh_iface_menu()`: sync Settings → Interface submenu on refresh.
  - `_select_interface(iface)`: set interface from Settings menu.
- Window min height bumped from 520 → 550.

### Changed
- Toolbar slimmed: removed Import, Export, Save list, Scan registered, Select all, Select none, Clear list buttons. Toolbar now has: + Add MAC, Filter entry, Start/Stop, Restore.

### Removed
- 7 toolbar buttons (Import, Export, Save list, Scan registered, Select all, Select none, Clear list) — now accessible via menus only.

## 2026-08-18 — Hostname rotation (v0.5.0)
### Added
- `src/rotation_engine.py`:
  - `get_hostname()` — returns current system hostname via `socket.gethostname()`.
  - `set_hostname(name)` — sets system hostname via `hostnamectl` (preferred) or `socket.sethostname()` fallback.
  - `restart_mdns()` — restarts mDNS/DNS-SD service via `systemctl restart avahi-daemon` or `systemctl restart mdns`.
  - `generate_hostname(pattern, mac)` — generates hostname from pattern with `{mac}`, `{mac_suffix}`, `{mac_hex}` placeholders.
  - `default_config()` updated with `hostname_enabled: False` and `hostname_pattern: "device-{mac_suffix}"`.
  - `RotationWorker` accepts `hostname_enabled` and `hostname_pattern` params; stores original hostname; changes hostname alongside MAC when enabled.
- `src/mac_changer.py`:
  - "Rotate hostname" checkbox (default off) in interval settings row.
  - Pattern text entry with placeholder `device-{mac_suffix}`.
  - Config persistence: `hostname_enabled` and `hostname_pattern` saved to `~/.config/mac-changer/config.json`.
  - Restore button reverts both MAC and hostname to original values.

### Changed
- `README.md` (feature list), `Spec.md` (0.5.0, R17), `docs/Changelog.md` (0.5.0), `docs/Version.md` (0.5.0), `docs/Context.md` (hostname rotation).

## 2026-08-18 — DHCP renewal fix + loaded-MAC display (v0.4.2)
### Fixed
- `src/rotation_engine.py`: `dhcp_renew()` rewritten — primary method is now `nmcli connection down/up` (fully tears down and re-establishes the connection with a fresh DHCP request, reliable after a MAC swap where the old lease is bound to the previous hardware address); falls back to `nmcli device reapply` (minor changes), then `dhclient` if available. Added `_get_nm_connection_name(iface)` helper to resolve the NM connection name for an interface.
### Added
- `src/rotation_engine.py`: `get_loaded_macs(cfg)` returns the in-memory MAC list as `[{mac, enabled}]` (normalized, deduplicated, valid-only); `loaded_macs_summary(cfg)` returns a human-readable count (e.g. `"8 MACs loaded (2 enabled, 6 disabled)"` or `"No MACs loaded"`).
- `src/mac_changer.py`: GUI top-bar `loaded_label` shows the loaded-MAC count on every `_update_current_mac` call. `_populate_config` logs the count on startup. `_toggle_rotation` logs the count before starting. `_import_list` and `_save_list` log updated counts after changes. `_rotation_done` refreshes the label when rotation stops.
- `RotationWorker` now logs each enabled MAC individually at startup: `[1] AA:BB:CC:DD:EE:FF`.

### Changed
- `README.md` (feature list + requirements), `docs/Changelog.md` 0.4.2, `docs/Version.md` 0.4.2, `Spec.md` 0.4.2 (R16 + architecture updated), `docs/Context.md` (DHCP strategy + runtime environment).

## 2026-08-16 — Firewall allow field + live detection (v0.4.1)
### Added
- `src/rotation_engine.py`:
  - `detect_firewall_allow(iface, probe=None)` — classifies the existing connectivity probe result: ok ⇒ `True`; gateway up + `No response from 1.1.1.1:80` ⇒ `False`; no IPv4 / gateway down / probe unavailable ⇒ `None` (never a false "firewalled" on a down link).
  - `firewall_map(path)` — load `{mac: bool}` from `RegisteredAddresses.json`, default `true`, tolerant of missing/malformed file.
  - `set_firewall_allow(mac, allowed)` — atomic single-field register update (mkstemp + `os.replace`); no-op on invalid/unknown MAC.
  - `load_registered` now exposes `firewall_allow`; `merge_register` is bool-aware (preserves `false`, defaults inserted entries to `true`).
  - `RotationWorker` gained a `register_path` param and persists non-`None` detection results after each rotation, reusing its own probe (no second SYN).
- `RegisteredAddresses.json`: all entries backfilled `firewall_allow: true` (JSON bool; sha `a761f615...` → `ad70668a...`, order/other fields preserved).
- `src/mac_changer.py`: per-row "FW" checkbox (column 4, ✕ moves to column 5) seeded from `firewall_map()`, collected on Save list, refreshed when a row's MAC is edited.
- `scripts/extract_macs.py`: emits `"firewall_allow": true` on regenerated registers.
- `tests/test_firewall_allow.py`: classification matrix, map defaults/coercion, bool-aware merge, atomic single-field set, invalid-MAC no-op, load round-trip, real-register shape. Wired as step 6 of `tests/test_import.sh`; `test_list_io`/`test_anonymize_hostnames` extended to assert the field.
### Changed
- `README.md` (register schema + "Firewall detection" section), `docs/Changelog.md` 0.4.1, `docs/Version.md` 0.4.1, `gui.sh` VERSION 0.4.1.
### Key implementation details
- Detection classification is probe-gated: `False` only when the gateway answers but the internet probe is blocked — a down gateway or absent IPv4 yields `None` (flag unchanged).
- Register writes stay atomic and single-field so hostname/last_seen from other writers are never clobbered.

## 2026-08-16 — Hostname anonymization (v0.4.0)
### Added
- `scripts/anonymize_hostnames.py` — blanks all non-RFC hostnames in `RegisteredAddresses.json` with unique deterministic dictionary words (MAC-hash indexed, collision-skipped); `scan` mode live-resolves real hostnames (ARP + reverse-DNS) over placeholders only; `--dry-run` default, atomic writes with `.bak`.
- `src/rotation_engine.py`: `is_valid_hostname(name)` (RFC 1123/952) and `blank_hostnames(devices, wordlist)`.
- `tests/test_anonymize_hostnames.py` (classification, determinism, uniqueness, no-loss round-trip, placeholder-only scan, atomic-write backup) wired into `tests/test_import.sh`.

## 2026-08-05 — MAC list enrichment (v0.3.0)
### Added
- Every row now shows the device's **hostname** and **last-seen** timestamp (from `RegisteredAddresses.json` + `data/last_seen.json`); **Sort by MAC / hostname**, **Select all/none**, display-only **filter box**, **Resolve hostnames** (register → ARP → reverse-DNS, background thread), and **Save list** merging back into the register (update/insert only, never shrinks, missing register recreated, atomic writes).
- Config `macs` entries grow to `{"mac", "enabled", "hostname", "last_seen_at"}` (all optional, backward compatible).
- `tests/test_list_enrichment.py` (hostname_map, merge update/insert/never-shrink, last_seen_for, enriched config round-trip, live-resolve fallback) and `tests/smoke_070.py`; wired into `tests/test_import.sh`.

## 2026-08-05 — Interface down-delay + scroll fix (v0.2.2)
### Added
- Configurable down-delay after each MAC change (Off/1s/2s/3s/5s/10s/15s/30s).
### Fixed
- MAC-list scroll crash with customtkinter 6.0.0 (`_check_if_valid_scroll` `AttributeError` on string Tcl pathnames) via a project-local `SafeScrollableFrame` subclass — no venv patch.

## 2026-08-01 — Last-seen detection + field rename (v0.2.1)
### Changed
- Registered-device JSON field `last_working_at` → `last_seen_at`; `scripts/extract_macs.py` now emits an empty value (was `"test"` placeholder) and its flag is `--last-seen-at`.
### Added
- `src/rotation_engine.py`:
  - `load_registered(path)` — parse `RegisteredAddresses.json` → `[{mac, hostname}]`, sorted, invalid skipped.
  - `probe_mac_seen(mac, active=False)` — `mac_tools.check_arp_cache(mac)`; optional `ping_device(ip)` confirmation.
  - `scan_registered(path, active, log_cb)` — single neighbor-table read indexed by MAC, stamps `last_seen_at` only on new sightings (never regresses), saves state, returns `(seen_count, total, results)`.
  - `load_seen_state()` / `save_seen_state()` / `seen_state_path()` — `data/last_seen.json` persistence.
- `src/mac_changer.py`: "Scan registered" button (beside Import/Export) running the scan in a daemon thread via `_scan_worker`.
- `tests/test_list_io.py`: register-key assertion updated to `last_seen_at`; added `load_registered`, seen-state round-trip, graceful `probe_mac_seen`, and missing-register scan tests.
### Key implementation details
- Scan reads the ARP/neighbor table **once** (not once per MAC) and indexes by normalized MAC — a full-table scan avoids one subprocess call per device.
- Observed state is stored separately from the generated register so regeneration and scans don't fight over the same file.

## 2026-08-01 — MAC list import/export + register extraction (v0.2.0)
### Added
- `src/rotation_engine.py`: `load_mac_list(path)` / `export_mac_list(path, macs)` — JSON list
  load/save with normalization, dedupe, invalid-entry filtering. `load_mac_list` tolerates both
  plain string arrays and object arrays carrying a `mac` key (the `RegisteredAddresses.json` format).
- `src/mac_changer.py`: "Import list" / "Export list" buttons beside "+ Add MAC" using
  `customtkinter.filedialog` (askopenfilename / asksaveasfilename). Import appends enabled rows
  and skips duplicates; export writes the editor's current MACs.
- `scripts/extract_macs.py`: reusable tab-separated register parser → `RegisteredAddresses.json`
  (`{"mac", "hostname", "last_working_at"}`), regex-locates MAC cells, dedupes, sorts by hostname.
- `tests/test_list_io.py`: round-trip + register-count tests; invoked by `tests/test_import.sh`.

### Key implementation details
- List I/O kept GUI-independent in the engine; only the file pickers live in the GUI layer.
- `last_working_at` field defaults to `"test"` (placeholder) until a real timestamp source is wired.

## 2026-08-01 — Root launcher fix (v0.1.1)
### Fixed
- `gui.sh` re-launched via `bash "$0"`, but `pkexec` resets the working directory on
  elevation → `./gui.sh: No such file or directory`. Changed to absolute path
  `bash "$DIR/gui.sh"`.

## 2026-08-01 — Initial build (v0.1.0)
### Added
- `src/rotation_engine.py` — GUI-independent engine: helpers, config load/save, `RotationWorker` thread.
- `src/mac_changer.py` — CustomTkinter GUI importing `rotation_engine`.
- `gui.sh` — root launcher.
- `requirements.txt`, `.gitignore`.
- Test/verification scripts under `tests/` and `scripts/`.

### Key implementation details
- Rotation worker (`src/rotation_engine.py`): `backup→change_mac→dhcp_renew→test_connection` loop, interval hold,
  fail-fast advance, stop flag for clean shutdown.
- Config: load/save JSON at `~/.config/mac-changer/config.json`.
- Engine split from GUI so root/headless tests run without `customtkinter`.
- mac_tools reuse via sys.path — no modifications to the shared library.
