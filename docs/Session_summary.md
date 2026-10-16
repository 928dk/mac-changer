# Session Summary

## 2026-08-23 — Auto-resolution + combined last-seen (v0.7.3)
### What was done
- Extended `resolve_hostnames_live()` to return `(hostnames, last_seen)` tuple — ARP cache MACs now get `last_seen_at` timestamps.
- Updated `_apply_resolved` to update both hostname labels and last-seen labels; persists last-seen via `save_seen_state`.
- Added auto-resolution timer (60s periodic) — resolves hostnames from DHCP cache without manual clicks. Skips during rotation, stops on close.
- Reduced duplicate DHCP logging — sniffer checks existing cache before logging.
- Updated callers: `scripts/anonymize_hostnames.py`, `tests/test_vpn_connectivity.py`, `tests/test_list_enrichment.py`.
- Created spec folder `.opencode/specs/107-mac-changer-auto-resolve/`.
- Backed up source files to `pre-107-backup.tar.zst`.
- Updated docs to v0.7.3.
- Verified: py_compile OK, all test suites pass.

## 2026-08-23 — DHCP hostname sniffer (v0.7.2)
### What was done
- Implemented passive DHCP hostname sniffer: scapy-based daemon thread listens for DHCP option-12 hostnames on all active interfaces.
- New engine helpers: `dhcp_hostnames_path()`, `load_dhcp_hostnames()`, `save_dhcp_hostnames()`, `start_dhcp_sniffer()`.
- Modified `resolve_hostnames_live()` to use DHCP cache as fallback before register.
- GUI integration: sniffer starts on app init (all interfaces, not just selected one).
- Graceful handling: PermissionError exits silently (no root = no sniffer), `_log_threadsafe` catches RuntimeError for safe teardown.
- Created spec folder `.opencode/specs/106-mac-changer-dhcp-sniffer/`.
- Backed up source files to `pre-106-backup.tar.zst`.
- Updated docs to v0.7.2.
- Verified: py_compile OK, all test suites pass.

## 2026-08-23 — DNS + row move fix (v0.7.1)
### What was done
- Fixed `_ptr_via_router` for on-link IPs: now tries system DNS (resolv.conf) and `getent hosts` as fallbacks when router dig fails. Added `_dig_reverse` helper to filter dig error output.
- Fixed `_move_selected`: now checks all row widgets for focus, not just entry and check.
- Created spec folder `.opencode/specs/105-mac-changer-dns-move-fix/`.
- Backed up source files to `pre-105-backup.tar.zst`.
- Updated docs to v0.7.1.
- Verified: py_compile OK, all test suites pass.

## 2026-08-23 — GUI enhancements (v0.7.0)
### What was done
- Fixed DNS resolution in sudo/pkexec context: `resolve_hostnames_live` now tries `_ptr_via_router` first, then `socket.gethostbyaddr` as fallback.
- Window size persistence: geometry saved to `~/.config/mac-changer/config.json` on close, restored on launch.
- Resizable MAC list frame: expands to fill available window space (was fixed 180px).
- Drag-to-resize column headers: drag handles between columns; widths persisted in config.
- File-based logging: weekly rotation to `logs/mac-changer.log`, 4-week retention.
- Created spec folder `.opencode/specs/104-mac-changer-gui-enhancements/`.
- Backed up source files to `pre-104-backup.tar.zst`.
- Updated all docs to v0.7.0 (README, Spec, Changelog, Version, Context, Code_change, Session_summary, Todo, Lessons_learned).
- Updated test mocks for `_ptr_via_router`; updated smoke_100 tooltip expectations.
- Verified: py_compile OK, all test suites pass.

## 2026-08-23 — Resolve hostnames fix (v0.6.1)
### What was done
- Fixed `resolve_hostnames_live` in `src/rotation_engine.py` to always check ARP cache for all MACs. Previously skipped ARP + reverse-DNS for MACs with existing hostnames in the register, causing "No new hostnames resolved" even when devices were online.
- Live-resolved hostnames now override register values; falling back to register hostnames only for offline devices.
- Created spec folder `.opencode/specs/103-mac-changer-resolve-hostnames/`.
- Backed up `src/rotation_engine.py` + `src/mac_changer.py` to `pre-103-backup.tar.zst`.
- Updated all docs to v0.6.1 (README, Spec, Changelog, Version, Context, Code_change, Session_summary, Todo, Agents, Lessons_learned).
- Verified: py_compile OK, all test suites pass (import.sh, list_enrichment, anonymize_hostnames, firewall_allow, list_io).

## 2026-08-18 — Native menu bar + toolbar cleanup (v0.6.0)
### What was done
- Added native `tk.Menu` bar with File / Edit / View / Settings / Help menus to `src/mac_changer.py`.
- File menu: Import (Ctrl+I), Export (Ctrl+E), Save (Ctrl+S), Exit (Ctrl+Q).
- Edit menu: Add MAC (Ctrl+A), Move up/down (Ctrl+↑/↓), Select all/none (Ctrl+Shift+A/N), Delete selected (Del), Clear list.
- View menu: Sort by submenu, Resolve hostnames, Scan registered, Filter focus (Ctrl+F).
- Settings menu: Interface submenu (synced with toolbar dropdown on refresh).
- Help menu: About dialog (version + project link), Open config folder (xdg-open).
- Slimmed toolbar: removed Import, Export, Save list, Scan registered, Select all, Select none, Clear list buttons. Toolbar now has: + Add MAC, Filter, Start/Stop, Restore.
- Window min height bumped from 520 → 550 for menu bar.
- Verified: py_compile OK, GUI smoke test passed.
- Updated all docs to v0.6.0 (README, Spec, Changelog, Version, Context, Code_change, Session_summary).

## 2026-08-18 — Hostname rotation (v0.5.0)
### What was done
- Created spec folder `.opencode/specs/101-mac-changer-hostname-rotation/` with spec.md, plan.md, tasks.md, description.json, graph-metadata.json.
- Backed up project to `$HOME/backups/mac-changer-pre-hostname-rotation-2026-08-18.tar.zst` (9.5MB).
- Added hostname helpers to `src/rotation_engine.py`: `get_hostname()`, `set_hostname()`, `restart_mdns()`, `generate_hostname()`.
- Updated `default_config()` with `hostname_enabled` and `hostname_pattern` fields.
- Updated `RotationWorker` to accept hostname params; stores original hostname; changes hostname alongside MAC when enabled.
- Added GUI controls: "Rotate hostname" checkbox and pattern text entry in interval settings row.
- Updated config persistence to save/load hostname settings.
- Updated restore button to revert both MAC and hostname.
- Verified: py_compile OK, hostname helpers tested, GUI smoke test passed.
- Updated all docs to v0.5.0 (README, Spec, Changelog, Version, Context, Code_change).

## 2026-08-18 — DHCP renewal fix + loaded-MAC display (v0.4.2)
### What was done
- Fixed `dhcp_renew()` in `src/rotation_engine.py` — rewrote to use `nmcli connection down/up` as primary method (fully re-establishes DHCP with new MAC after a swap, where the old lease is bound to the previous hardware address); falls back to `nmcli device reapply` then `dhclient`. Added `_get_nm_connection_name(iface)` helper.
- Added loaded-MAC list display: `get_loaded_macs(cfg)` returns `[{mac, enabled}]`; `loaded_macs_summary(cfg)` returns a human-readable count (e.g. "8 MACs loaded (2 enabled, 6 disabled)").
- GUI: top-bar `loaded_label` shows the count; rotation start log lists each enabled MAC individually; config population, import, and save log updated counts.
- Updated all docs to v0.4.2 (README, Changelog, Version, Spec, Context, Code_change, Agents, Session_summary).

## 2026-08-16 — Firewall allow field + live detection (v0.4.1)
### What was done
- Backed up the project to `$HOME/backups/backup-2026-08-16-mac-changer-pre-firewall-allow.tar.zst` before any edit.
- Added `firewall_allow: bool` to every `RegisteredAddresses.json` entry (all backfilled `true`, JSON bool; sha `a761f615...` → `ad70668a...`, order preserved).
- Engine: `detect_firewall_allow` (classifies the existing connectivity probe: ok ⇒ `true`, gateway-up + internet probe blocked ⇒ `false`, indeterminate ⇒ `None`), `firewall_map`, atomic single-field `set_firewall_allow`, bool-aware `merge_register` (`false` preserved), `load_registered` field exposure, `RotationWorker` probe-reuse persistence.
- GUI: per-row "FW" checkbox (col 4, ✕ → col 5), seeded/persisted on Save list, refreshed on MAC edit.
- `scripts/extract_macs.py` emits the field; `tests/test_firewall_allow.py` (14 tests) wired as step 6 of `tests/test_import.sh`; list-I/O + anonymize tests extended.
- Docs updated to 0.4.1 (README, Changelog, Version, gui.sh).
- Packet `.opencode/specs/098-mac-changer-firewall-allow/` authored, then its docs rewritten to current template structure so `validate.sh --strict` passes (0 errors / 0 warnings, exit 0).
- Verified: py_compile OK, `test_firewall_allow.py` 14/14, `test_import.sh` 6/6 ALL CHECKS PASSED.

### Follow-up (same day)
- Synchronized the other project markdown docs (Agents.md, Spec.md, docs/Code_change.md, Todo.md, Context.md, Quick_start.md, Session_summary.md) with the 0.4.1 state.

## 2026-08-01 — Initial Build
### What was done
- Authored spec 066 (`.opencode/specs/066-mac-changer/`) Level 1 docs.
- Scaffolded `~/projects/Client/mac-changer/` per `~/Project_template.md`.
- Implemented `src/rotation_engine.py` (GUI-independent engine: helpers + config + `RotationWorker`) and `src/mac_changer.py` (CustomTkinter GUI), plus `gui.sh`.
- Verified: py_compile, import chain (mac_tools reuse), Xvfb GUI smoke as root,
  dummy-interface rotation + restore.
- Validated spec folder (`validate.sh --strict` PASS).

### Follow-up (same day)
- Fixed `gui.sh` relaunch bug: `pkexec` resets CWD, so `bash "$0"` failed with
  `./gui.sh: No such file or directory`. Now uses absolute path `bash "$DIR/gui.sh"`.
- Root GUI smoke verified on desktop (`./gui.sh --smoke` PASS — window builds + closes cleanly).

### Next session
- Review `docs/Lessons_learned.md`; consider wall-clock mode / systemd unit backlog items.
