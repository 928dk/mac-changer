# Context.md — Architecture & Background

## What / Why
mac-changer is a standalone companion to fisheye-gui that automates periodic MAC
rotation with connectivity verification. Where fisheye-gui exposes one-shot MAC tools,
mac-changer holds a chosen MAC for an interval, switches, and health-checks the network
after each change. Optionally rotates the system hostname alongside MAC changes for
enhanced privacy. As of v0.7.0, the GUI persists window geometry and column widths,
resizes the MAC list to fill available space, and logs to a weekly-rotating file.

## Architecture

```
gui.sh                 root launcher (venv + deps + pkexec/sudo)
  └─ src/mac_changer.py
       ├─ tk.Menu (native)      File / Edit / View / Settings / Help
       │    ├─ File: Import, Export, Save, Exit
       │    ├─ Edit: Add, Move up/down, Select all/none, Delete selected, Clear
       │    ├─ View: Sort by ▸, Resolve hostnames, Scan registered, Filter
       │    ├─ Settings: Interface ▸
       │    └─ Help: About, Open config folder
       ├─ UI (main thread)      CTk widgets, after(0, ...) updates
       │    ├─ Interface selector + Refresh + Current MAC + Loaded count
       │    ├─ MAC list (header + scrollable rows with per-row FW checkbox)
       │    ├─ + Add MAC, Filter entry
       │    ├─ Interval / Down delay / Hostname rotation settings
       │    └─ Start/Stop + Restore + Status
       ├─ RotationWorker (thread)  backup→change_mac→hostname→dhcp_renew→test_connection→detect_firewall_allow loop
        ├─ helpers               get_interface_ip, get_gateway, dhcp_renew, test_connection,
        │                        detect_firewall_allow, firewall_map, set_firewall_allow,
        │                        get_loaded_macs, loaded_macs_summary,
        │                        hostname_map, resolve_hostnames_live, last_seen_for, merge_register,
        │                        get_hostname, set_hostname, restart_mdns, generate_hostname
       └─ config                ~/.config/mac-changer/config.json
lib/mac_tools (imported via sys.path from ~/projects/Client/fisheye-gui)
       change_mac, backup_mac, get_last_backup, change_mac_restore,
       get_current_mac, ping_device, active_internet_probe, ...
```

## Key Decisions
- **Reuse over copy**: import `mac_tools` from the sibling fisheye-gui project via
  `sys.path.insert(0, "~/projects/Client/fisheye-gui")`. Parent app stays unmodified.
- **Interval rotation** (not wall-clock): each MAC held a selectable duration.
- **Connectivity gate**: IPv4 up + gateway ping + `active_internet_probe`
  (scapy SYN → 1.1.1.1:80). Any failure → advance to next MAC immediately.
- **DHCP renewal**: `nmcli connection down/up` is the primary method (fully re-establishes
  DHCP with new MAC after a swap); falls back to `nmcli device reapply` then `dhclient`.
- **Hostname rotation**: optional system hostname change with configurable pattern;
  mDNS restart after change; original hostname stored for restore.
- **Native menu bar**: `tk.Menu` for OS-native menus; toolbar slimmed to core controls;
  keyboard shortcuts for all common actions.
- **Backup/restore** uses the shared `flow_database.sqlite` `mac_backups` table, so the
  original MAC survives across app restarts.
- **Root by design**: `change_mac` needs euid 0; `gui.sh` enforces it.

## Runtime Environment
- Python 3.10+ (venv at `.venv`), CustomTkinter, scapy.
- Linux: `ip`, NetworkManager (preferred) or `dhclient`, `ip route`, `hostnamectl`.
- Config dir: `~/.config/mac-changer/`.

## Data
- `flow_database.sqlite` (`~/projects/Client/data/`) — `mac_backups` table (shared).
- `~/.config/mac-changer/config.json` — UI state (interface, MAC list, interval, hostname settings).
- `RegisteredAddresses.json` (project root) — registered devices `{mac, hostname, last_seen_at, firewall_allow}` (generated register, sorted by hostname).
- `data/last_seen.json` — runtime `{mac: ISO timestamp}` observations from "Scan registered", gitignored.
