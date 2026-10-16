# Version

| Field | Value |
|-------|-------|
| **Project** | mac-changer |
| **Version** | 0.8.0 |
| **Status** | Stable |
| **Date** | 2026-08-24 |

## Version History
- **0.8.0** (2026-08-24) — Onboarding UX + bulk management: File → New List (clears list + config), empty-state persistent label with instructions, Discover devices button with checkbox selection dialog (ARP + DHCP scan), DHCP sniffer toggle in Settings menu, configurable auto-resolve interval (15s/30s/60s/120s), discover_hostnames / discover_devices_v2 / scan_dhcp_cache / probe_arp_cache engine helpers, import deduplication (skips duplicate MACs), import summary log, persist original hostname for restore, version single source (__version__ in rotation_engine.py), DHCP sniffer accessible from menu bar, fixed hardcoded config folder path, fixed stale loaded-macs summary after import.
- **0.7.3** (2026-08-23) — Combined hostname resolution + last-seen update: resolving hostnames now also stamps `last_seen_at` for online devices. Auto-resolution timer (60s) periodically resolves hostnames from DHCP cache without manual clicks. Reduced duplicate DHCP logging.
- **0.7.2** (2026-08-23) — DHCP hostname sniffer: passive scapy-based DHCP option-12 capture for MAC→hostname resolution; persists to `dhcp_hostnames.json`; integrated into `resolve_hostnames_live()` as fallback before register.
- **0.7.1** (2026-08-23) — DNS fix: `_ptr_via_router` now tries system DNS + `getent hosts` for on-link IPs; filters dig error output. Row move fix: `_move_selected` checks all row widgets, not just entry and check.
- **0.7.0** (2026-08-23) — GUI enhancements: DNS fix (try `_ptr_via_router` first, then `socket.gethostbyaddr` as fallback for sudo/pkexec); window size persistence; resizable MAC list frame (expands to fill); drag-to-resize column headers (widths persisted to config); weekly file-based logging to `logs/mac-changer.log` with 4-week retention.
- **0.6.1** (2026-08-23) — Fix: `resolve_hostnames_live` now always checks ARP cache for all MACs; live-resolved hostnames override register values, falling back to register for offline devices. Previously skipped ARP resolution for MACs with existing hostnames, causing "No new hostnames resolved" even when devices were online.
- **0.6.0** (2026-08-18) — Native menu bar (File/Edit/View/Settings/Help) with keyboard shortcuts; toolbar slimmed to core controls (+Add MAC, Filter, Start/Stop, Restore); Move up/down reorder; Delete selected; About dialog; Open config folder; Settings → Interface submenu.
- **0.5.0** (2026-08-18) — Hostname rotation: optional system hostname change alongside MAC rotation with configurable pattern (`{mac}`, `{mac_suffix}`, `{mac_hex}`); mDNS restart after change; original hostname stored for restore; GUI checkbox + pattern entry; config persistence (`hostname_enabled`, `hostname_pattern`); restore button reverts both MAC and hostname.
- **0.4.2** (2026-08-18) — DHCP renewal fix for post-MAC-change: `dhcp_renew` now uses `nmcli connection down/up` (fully re-establishes DHCP with new MAC) as primary method, falling back to `nmcli device reapply` then `dhclient`; added `_get_nm_connection_name` helper. Loaded-MAC list display: `get_loaded_macs` / `loaded_macs_summary` engine helpers; GUI top-bar label shows count (e.g. "8 MACs loaded (2 enabled, 6 disabled)"); rotation start log lists each enabled MAC.
- **0.4.1** (2026-08-16) — Firewall allow field + live detection: `firewall_allow: bool` on all register entries (backfilled, default `true`); `detect_firewall_allow` classifies the rotation connectivity probe (ok ⇒ allowed, gateway-up + probe-blocked ⇒ firewalled, indeterminate ⇒ unchanged); `RotationWorker` persists results via atomic `set_firewall_allow`; bool-aware `merge_register` preserves `false`; GUI "FW" checkbox per row; `tests/test_firewall_allow.py` (step 6 of `test_import.sh`).
- **0.4.0** (2026-08-16) — Hostname anonymization: `scripts/anonymize_hostnames.py` blanks all non-RFC hostnames in `RegisteredAddresses.json` with unique deterministic dictionary words (MAC-hash indexed) and a `scan` mode that live-resolves real hostnames (ARP + reverse-DNS) over placeholders only; atomic writes with `.bak`; `is_valid_hostname` + `blank_hostnames` engine helpers; `tests/test_anonymize_hostnames.py`.
- **0.3.0** (2026-08-05) — MAC list enrichment: hostname + last-seen per row, sort by MAC/hostname, select all/none, display-only filter, live hostname resolution (register → ARP → reverse-DNS), Save list merges back into `RegisteredAddresses.json` (never shrinks), remembered import/export paths.
- **0.2.2** (2026-08-05) — Interface down-delay setting (Off/1s/2s/3s/5s/10s/15s/30s) applied during rotation; MAC-list scroll crash fixed via `SafeScrollableFrame` subclass.
- **0.2.1** (2026-08-01) — Last-seen detection (`last_seen_at`), "Scan registered" GUI button, `data/last_seen.json` persistence.
- **0.2.0** (2026-08-01) — MAC list import/export, `RegisteredAddresses.json` register, `scripts/extract_macs.py` parser, `tests/test_list_io.py`.
- **0.1.1** (2026-08-01) — `gui.sh` relaunch fix via absolute path; root GUI smoke verified.
- **0.1.0** (2026-08-01) — Initial release: interval MAC rotation, connectivity gate, restore, config persistence.
