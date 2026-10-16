# MAC Changer — Interval MAC Rotation App

## Overview
Standalone root GUI app that rotates an interface's MAC address on a selectable interval.
After every change it renews DHCP and tests connectivity (interface IP + gateway + internet);
if the new MAC is unhealthy it falls through to the next configured MAC automatically.
Reuses fisheye-gui's proven MAC library — no code duplication. The rotation engine
(`src/rotation_engine.py`) is GUI-independent; the GUI (`src/mac_changer.py`) is a thin front-end.

## Features
- **Interval rotation** — hold each MAC for 5m / 15m / 30m / 1h / 2h / 6h / 12h / 24h / custom
- **Per-MAC selection** — checkbox per list entry; only enabled MACs participate in rotation
- **Native menu bar** — File / Edit / View / Settings / Help menus with keyboard shortcuts
- **Enriched list** — every entry shows a resolved **hostname** and **last-seen** timestamp; sort by MAC or hostname, filter by MAC/hostname substring (display-only), and bulk select/deselect all
- **Firewall allow column** — every entry has a "FW" checkbox seeded from the register (`firewall_allow`); ticked = the device is allowed through the firewall, saved back on "Save list"
- **Resolve hostnames** — checks ARP cache + reverse-DNS for all MACs; live-resolved hostnames override register values, falling back to register hostnames for offline devices
- **Save list** — merges the current list back into `RegisteredAddresses.json` (update/insert only — never shrinks the register)
- **Last-seen detection** — "Scan registered" probes the kernel neighbor table and reports which registered devices are currently on the network, stamping real `last_seen_at` timestamps
- **Connectivity gate** — IP + gateway + internet check after each change; failure advances immediately
- **Interface down-delay** — optional pause (Off / 1s / 2s / 3s / 5s / 10s / 15s / 30s) between link-down and link-up on each rotation, letting the network release the previous MAC before reconnecting
- **Original MAC backup + restore** — first switch records the original; Restore button reverts
- **Hostname rotation** — optional: change system hostname alongside MAC address with configurable pattern (`{mac}`, `{mac_suffix}`, `{mac_hex}`)
- **Persistent config** — interface, MAC list, interval, down-delay, hostname, window size, and column widths saved to `~/.config/mac-changer/config.json`
- **Loaded-MAC count** — top-bar label shows how many MACs are loaded and how many are enabled (e.g. "8 MACs loaded (2 enabled, 6 disabled)"); rotation start log lists each enabled MAC individually
- **Move up / Move down** — reorder MACs in the list via Edit menu or `Ctrl+↑`/`Ctrl+↓`
- **Delete selected** — remove all checked rows via Edit menu or `Del` key
- **About dialog** — version, project link
- **Open config folder** — opens `~/.config/mac-changer/` in system file manager
- **Live log pane** — every change, renewal, and test result is logged in-app; weekly file rotation to `logs/mac-changer.log`
- **Resizable columns** — drag column borders in the header to resize; widths persisted across sessions
- **Resizable MAC list** — list expands to fill available window space

## Registered devices list

`RegisteredAddresses.json` (project root) holds the registered devices as
`{"mac", "hostname", "last_seen_at", "firewall_allow"}` objects, sorted by hostname. It is generated from
a tab-separated device export (for example `devices.txt`) by the reusable parser:

```bash
python3 scripts/extract_macs.py "devices.txt" --out RegisteredAddresses.json
```

When the app's "Scan registered" button (or `scan_registered()` in the engine) observes a
device in the neighbor table, it stamps a real timestamp into `data/last_seen.json`
(`{mac: ISO timestamp}`). This file is separate from the generated register so re-running the
extractor never clobbers observed data; timestamps are only ever set forward.

### Hostname anonymization

Most register hostnames are not real hostnames — they are labels assigned by a company or
organisation (for example asset or account numbers), or by a public Wi-Fi network that
registers each device and limits how long or how much each one may use.
`scripts/anonymize_hostnames.py` replaces every non-RFC hostname with a stable
dictionary word derived from the device MAC (unique, deterministic across re-runs), so the
register is safe to commit:

```bash
# Preview (writes nothing):
python3 scripts/anonymize_hostnames.py blank --dry-run

# Apply (atomic write + RegisteredAddresses.json.bak backup):
python3 scripts/anonymize_hostnames.py blank
```

The `scan` mode recovers the devices' real hostnames from the network (ARP cache +
reverse-DNS) and inserts them over the dictionary-word placeholders only — real/curated
hostnames are never overwritten. Use the same wordlist that produced the placeholders:

```bash
python3 scripts/anonymize_hostnames.py scan --dry-run   # preview
python3 scripts/anonymize_hostnames.py scan             # apply
```

`--register PATH` and `--wordlist PATH` override the defaults; `--dry-run` never writes.

### Firewall allow detection

Every register entry carries a `firewall_allow: bool` flag (default `true`) recording whether the
device is permitted through the firewall. The GUI shows it as the "FW" checkbox next to each row
(ticked = allowed); "Save list" writes the flags back into the register.

During interval rotation the app already impersonates each registered MAC and runs its connectivity
gate (interface IP + gateway ping + internet probe to 1.1.1.1:80). That probe is a live per-MAC
firewall measurement, classified by `detect_firewall_allow(iface)` as:

| Probe result | `firewall_allow` |
|--------------|------------------|
| Connectivity ok | `true` (allowed) |
| Gateway up, internet probe blocked (`No response from 1.1.1.1:80`) | `false` (firewalled) |
| No IPv4 / gateway down / probe unavailable | unchanged (indeterminate) |

Only gateway-up + probe-blocked writes `false`; a down link or gateway never flips the flag.
`RotationWorker` records each non-indeterminate result after the connectivity test via
`set_firewall_allow(mac, allowed)` — an atomic single-field register update. Detection only covers
MACs the machine actually rotates to; devices that are never impersonated cannot be measured from
the LAN.

## Quick Start

```bash
cd ~/projects/Client/mac-changer
./gui.sh
```

The launcher creates a virtual environment, installs dependencies if missing, and re-runs
itself as root via `pkexec` (sudo fallback).

## Requirements

- Python 3.10+ with `tkinter`
- Linux (`ip`, `iproute2`); root privileges for MAC changes
- NetworkManager (preferred) or `dhclient` for DHCP renewal

### Python Dependencies

| Package | Purpose |
|---------|---------|
| `customtkinter` | UI framework |
| `scapy` | Internet connectivity probe |

See `docs/INSTALL.md` and `docs/Quick_start.md` for details.

## License

GNU General Public License v2.0 (consistent with the fisheye-gui ecosystem)
