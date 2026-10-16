# Research.md — Design Notes

## Timing Model
- **Interval rotation** (approved): each enabled MAC is held for the selected duration,
  then the engine switches to the next. The timer rotates while running.
- Wall-clock scheduling (e.g. "switch at 02:00") is explicitly out of scope for v0.1.

## Connectivity Gate
Three-stage test after every `change_mac`:
1. **IPv4 up** — `get_interface_ip(iface)` must return a non-loopback IPv4 address.
2. **Gateway ping** — default gateway from `ip route show default` must answer one ping.
3. **Internet probe** — `mac_tools.active_internet_probe` (scapy SYN → 1.1.1.1:80).

Any stage fails ⇒ log reason ⇒ advance to next enabled MAC immediately (no waiting the interval).

## DHCP Renewal Drivers
- Prefer `nmcli connection down <conn>` then `nmcli connection up <conn>` (NetworkManager) — fully tears down and re-establishes the connection with a fresh DHCP request, reliable after a MAC swap where the old lease is bound to the previous hardware address.
- Fall back to `nmcli device reapply <iface>` (works for minor changes but may not trigger new DHCP after a MAC change).
- Fall back to `dhclient -r <iface>` then `dhclient <iface>` (non-NM setups).

## Reuse Strategy
`sys.path.insert(0, os.path.expanduser("~/projects/Client/fisheye-gui"))` then
`from lib import mac_tools`. Verified importable in a standalone venv. Parent files untouched.

## Backup/Restore
First successful switch calls `mac_tools.backup_mac(iface, original)` (stores to the shared
`mac_backups` table). Restore reads `get_last_backup(iface)` and applies via
`change_mac_restore(iface)`.

## Testing Isolation
All automated rotation tests run on a synthetic dummy interface:
`ip link add macchg0 type dummy`. The real NIC is never touched during verification.
