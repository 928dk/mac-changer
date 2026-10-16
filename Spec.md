---
title: "mac-changer"
version: "0.6.1"
updated: "2026-08-23"
---

# Spec.md — mac-changer

## Purpose
A standalone, root-elevated desktop app that periodically rotates a network interface's
MAC address and verifies connectivity after each change, falling through to the next
configured MAC when the current one fails. Optionally rotates the system hostname
alongside MAC changes for enhanced privacy.

## Requirements
- **R1** Launch as a root GUI via `./gui.sh` (pkexec, sudo fallback).
- **R2** Select the target interface from the available list; show current MAC.
- **R3** Maintain an editable MAC list with per-entry enable checkboxes (add/remove/edit, validated).
- **R4** Select an interval (5m/15m/30m/1h/2h/6h/12h/24h/custom) for holding each MAC.
- **R5** Start/Stop toggle drives a background rotation thread.
- **R6** After each change: DHCP renew then test connectivity (IPv4 up + gateway ping + internet probe).
- **R7** On test failure, log the reason and immediately advance to the next enabled MAC.
- **R8** Backup the original MAC on the first switch; provide a Restore original button.
- **R9** Persist interface/MAC list/interval/hostname settings to `~/.config/mac-changer/config.json`.
- **R10** Import a MAC list from JSON (plain string array or `{"mac",...}` object array) via file picker; append enabled, deduplicated rows.
- **R11** Export the current MAC list to JSON via file picker; normalized and deduplicated.
- **R12** Ship `RegisteredAddresses.json` plus `scripts/extract_macs.py` to regenerate it from any tab-separated device export.
- **R13** Detect which registered devices are currently on the network (`scan_registered` / `probe_mac_seen` via the kernel neighbor table) and stamp real `last_seen_at` timestamps into a separate runtime store (`data/last_seen.json`).
- **R14** Record a `firewall_allow: bool` flag on every register entry (default `true`; existing entries backfilled) and expose it as a per-row "FW" checkbox in the GUI, saved back via "Save list".
- **R15** Live-detect firewall state per MAC during interval rotation: `detect_firewall_allow` classifies the existing connectivity probe (ok ⇒ `true`; gateway up + internet probe blocked ⇒ `false`; no IPv4 / gateway down / probe unavailable ⇒ `None`), and `RotationWorker` persists non-`None` results atomically via `set_firewall_allow`.
- **R16** Show loaded-MAC count in the GUI top bar (e.g. "8 MACs loaded (2 enabled, 6 disabled)"); log each enabled MAC at rotation start.
- **R17** Optional hostname rotation: change system hostname alongside MAC address using configurable pattern (`{mac}`, `{mac_suffix}`, `{mac_hex}`); mDNS restart after change; restore original hostname on Restore.
- **R18** Clear list button: remove all MACs from the in-memory list (does not touch the JSON on disk).
- **R19** Native menu bar (File / Edit / View / Settings / Help) with keyboard shortcuts; toolbar slimmed to core controls (+ Add MAC, Filter, Start/Stop, Restore).
- **R20** Move up / Move down reorder: change MAC priority order via Edit menu or `Ctrl+↑`/`Ctrl+↓`.
- **R21** Delete selected: remove all checked (enabled) rows via Edit menu or `Del` key.
- **R22** About dialog (version, project link) and Open config folder (opens `~/.config/mac-changer/` in file manager).
- **R23** Resolve hostnames checks ARP cache for all MACs; live-resolved hostnames override register values, falling back to register hostnames for offline devices.

## Architecture
- `src/rotation_engine.py` — GUI-independent engine: helpers (`get_interface_ip`, `get_gateway`, `dhcp_renew`, `test_connection`, `get_loaded_macs`, `loaded_macs_summary`, `get_hostname`, `set_hostname`, `restart_mdns`, `generate_hostname`), config load/save, list load/export (`load_mac_list`, `export_mac_list`), registered-device load/detect (`load_registered`, `probe_mac_seen`, `scan_registered`, `load_seen_state`, `save_seen_state`), firewall-allow (`detect_firewall_allow`, `firewall_map`, `set_firewall_allow`, bool-aware `merge_register`), `RotationWorker` thread.
- `src/mac_changer.py` — CustomTkinter GUI with `tk.Menu` native menu bar (File / Edit / View / Settings / Help); toolbar with + Add MAC, Filter, Start/Stop, Restore; keyboard shortcuts.
- `lib/mac_tools` (imported from `~/projects/Client/fisheye-gui` via `sys.path`) — MAC ops + `check_arp_cache`.
- `scripts/extract_macs.py` — reusable tab-separated register parser → `RegisteredAddresses.json`.
- `gui.sh` — root launcher (venv, deps, pkexec/sudo).

## Verification
- `python -m py_compile src/mac_changer.py src/rotation_engine.py`
- Import check: mac_tools reuse via sys.path.
- `tests/test_list_io.py` — load/export round-trip, dedupe, invalid-entry filtering, register count, `load_registered`, seen-state round-trip, graceful probe/scan.
- `tests/test_firewall_allow.py` — probe classification matrix (4 outcomes), map defaults/coercion, bool-aware merge (`false` preserved), atomic single-field set, invalid-MAC no-op, load round-trip, real-register backfill shape.
- `tests/test_anonymize_hostnames.py` — blank/scan classification, determinism, uniqueness, no-loss round-trip, atomic-write backup.
- `tests/test_import.sh` — 6-step import + py_compile verification (ALL CHECKS PASSED).
- Xvfb headless GUI smoke test as root + desktop root smoke (`./gui.sh --smoke` PASS).
- Dummy-interface (`macchg0`) rotation + restore test — real NIC untouched.
- Hostname rotation: `get_hostname()`, `generate_hostname()`, `set_hostname()` helpers verified.
- Menu bar: `tk.Menu` native menu bar with keyboard shortcuts verified.
