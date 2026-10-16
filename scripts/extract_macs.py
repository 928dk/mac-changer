#!/usr/bin/env python3
"""Extract registered MAC addresses from a tab-separated device export into RegisteredAddresses.json.

Parses tab-separated rows where the MAC is one of the columns (the export may
carry extra leading or trailing columns). The MAC cell is located by regex and
the hostname is taken as the cell two positions before the MAC, falling back to
the cell immediately before it when that is empty.

Emits a JSON array sorted by hostname, one object per unique MAC:

    [{"mac": "AA:BB:CC:DD:EE:FF", "hostname": "...", "last_seen_at": "", "firewall_allow": true}]

`last_seen_at` is left empty by the extractor — the app fills it at runtime from
`data/last_seen.json` when a device is observed on the network. New devices
default to `firewall_allow: true` (allowed through the firewall).

Usage:
    python3 scripts/extract_macs.py [devices.txt] [--out OUT.json] [--last-seen-at VAL]
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")

# Try to reuse the shared fisheye-gui MAC helpers; fall back to inline copies.
def _fisheye_candidates():
    here = Path(__file__).resolve()
    cands = []
    for p in here.parents:
        cands.append(p / "fisheye-gui")
        cands.append(p / "lib")
    cands.append(Path.home() / "projects" / "Client" / "fisheye-gui")
    return [str(c) for c in cands]

try:
    _loaded = False
    for _cand in _fisheye_candidates():
        if os.path.isdir(_cand) and _cand not in sys.path:
            sys.path.insert(0, _cand)
    from lib import mac_tools
    normalize_mac = mac_tools.normalize_mac
    is_valid_mac = mac_tools.is_valid_mac
    _loaded = True
except Exception:
    pass

if not _loaded:
    def normalize_mac(mac: str) -> str:
        return ":".join(p for p in mac.strip().replace("-", ":").upper().split(":") if p)

    def is_valid_mac(mac: str) -> bool:
        return bool(_MAC_RE.match(mac.strip()))


def parse_register(path, last_seen_at=""):
    """Return [{mac, hostname, last_seen_at, firewall_allow}] deduped and sorted by hostname."""
    entries = []
    seen = set()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            cells = [c.strip() for c in line.rstrip("\n").split("\t")]
            mac_idx = next((i for i, c in enumerate(cells) if _MAC_RE.match(c)), None)
            if mac_idx is None:
                continue
            mac = normalize_mac(cells[mac_idx])
            if mac in seen:
                continue
            hostname = ""
            if mac_idx - 2 >= 0 and cells[mac_idx - 2]:
                hostname = cells[mac_idx - 2]
            elif mac_idx - 1 >= 0 and cells[mac_idx - 1]:
                hostname = cells[mac_idx - 1]
            seen.add(mac)
            entries.append({
                "mac": mac,
                "hostname": hostname,
                "last_seen_at": last_seen_at,
                "firewall_allow": True,
            })
    entries.sort(key=lambda e: e["hostname"].lower())
    return entries


def write_json(entries, out_path) -> bool:
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
            f.write("\n")
        return True
    except OSError as e:
        print(f"[-] Failed to write {out_path}: {e}", file=sys.stderr)
        return False


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="Path to the device export .txt (default: newest devices*.txt)")
    parser.add_argument("--out", default="RegisteredAddresses.json", help="Output JSON path")
    parser.add_argument("--last-seen-at", default="",
                        help="Default value for the last_seen_at field (default: empty)")
    args = parser.parse_args(argv)

    src = args.path
    if not src:
        here = Path(__file__).resolve().parents[1]
        candidates = sorted(here.glob("devices*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print("[-] No devices*.txt found — pass a path explicitly", file=sys.stderr)
            return 2
        src = str(candidates[0])
        print(f"[i] Using newest register: {src}")

    entries = parse_register(src, last_seen_at=args.last_seen_at)
    if not entries:
        print("[-] No MACs extracted", file=sys.stderr)
        return 1

    ok = write_json(entries, args.out)
    if not ok:
        return 1
    print(f"[+] {len(entries)} unique MACs -> {args.out}")
    for e in entries[:3]:
        print(f"    {e['mac']}  {e['hostname']}")
    if len(entries) > 6:
        print("    ...")
    for e in entries[-3:]:
        print(f"    {e['mac']}  {e['hostname']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
