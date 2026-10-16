# Todo

## In Progress
- [x] v0.1.0 initial build (interval rotation, connectivity gate, restore, config)
- [x] v0.1.1 root launcher fix (pkexec CWD reset → absolute-path relaunch)
- [x] v0.2.0 MAC list import/export + register extraction (`RegisteredAddresses.json`)
- [x] v0.2.1 last-seen detection (`scan_registered`, `data/last_seen.json`, field rename)
- [x] v0.2.2 interface down-delay setting + MAC-list scroll crash fix
- [x] v0.3.0 MAC list enrichment (hostname + last-seen per row, sort, select all/none, filter, resolve, Save list merge)
- [x] v0.4.0 hostname anonymization (`scripts/anonymize_hostnames.py` blank/scan, atomic + `.bak`)
- [x] v0.4.1 firewall allow field + live detection (`firewall_allow`, FW checkbox, `detect_firewall_allow`/`set_firewall_allow`)
- [x] v0.4.2 DHCP renewal fix (`nmcli connection down/up` primary) + loaded-MAC count display
- [x] v0.5.0 hostname rotation (hostnamectl + Avahi/mDNS restart per MAC change)
- [x] v0.6.0 native menu bar (File/Edit/View/Settings/Help) + toolbar cleanup + keyboard shortcuts
- [x] v0.6.1 resolve hostnames fix (ARP cache check for all MACs, register fallback)
- [x] v0.7.0 GUI enhancements (DNS fix, window size persistence, resizable frame, drag-resize columns, file logging)
- [x] v0.7.1 DNS + row move fix (on-link IP fallback, all-row-widget focus check)
- [x] v0.7.2 DHCP hostname sniffer (passive scapy capture, option-12 persistence, resolve chain integration)
- [x] v0.7.3 auto-resolution + combined last-seen (60s timer, tuple return, duplicate log fix)

## Backlog (future)
- [ ] Active (ping-confirmed) scan toggle from the GUI (engine already supports `active=True`)

## Done
- [x] Spec 066 authored and validated
- [x] Project scaffolded per `~/Project_template.md`
- [x] Implementation + verification complete (dummy-interface tests)
- [x] Root GUI smoke verified on desktop (`./gui.sh --smoke` PASS)
