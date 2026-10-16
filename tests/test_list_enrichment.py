#!/usr/bin/env python3
"""Spec 070 engine tests: hostname_map, resolve_hostnames_live, last_seen_for,
merge_register, and enriched config round-trip (no root required)."""
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

DIR = Path(__file__).resolve().parents[1]
FISHEYE_GUI = DIR.parent / "fisheye-gui"

for p in (str(FISHEYE_GUI), str(DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import rotation_engine as re


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_hostname_map_from_file():
    with tempfile.TemporaryDirectory() as d:
        reg = os.path.join(d, "register.json")
        _write_json(reg, [
            {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "Host-A", "last_seen_at": ""},
            {"mac": "aa-bb-cc-dd-ee-ff", "hostname": ""},
            "not-valid-mac",
        ])
        names = re.hostname_map(reg)
        assert names == {"AA:BB:CC:DD:EE:FF": "Host-A"}, names
    print("  OK: hostname_map from register (dedupe + skip empty hostname)")


def test_hostname_map_missing_file():
    assert re.hostname_map("/no/such/register.json") == {}
    print("  OK: hostname_map on missing file returns {}")


def test_merge_register_update_insert_no_shrink():
    with tempfile.TemporaryDirectory() as d:
        reg = os.path.join(d, "register.json")
        _write_json(reg, [
            {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "Old-Name", "last_seen_at": ""},
            {"mac": "00:11:22:33:44:55", "hostname": "Keep-Me",
             "last_seen_at": "2026-01-01T00:00:00"},
        ])
        changed = re.merge_register([
            {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "New-Name",
             "last_seen_at": "2026-08-05T12:00:00"},
            {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "New-Name",
             "last_seen_at": "2026-08-05T12:00:00"},
            {"mac": "66:77:88:99:AA:BB", "hostname": "Brand-New", "last_seen_at": ""},
        ], reg)
        data = _read_json(reg)
        by_mac = {e["mac"]: e for e in data}
        assert changed == 3, changed  # 1 update + 1 duplicate row + 1 insert
        assert by_mac["AA:BB:CC:DD:EE:FF"]["hostname"] == "New-Name"
        assert by_mac["AA:BB:CC:DD:EE:FF"]["last_seen_at"] == "2026-08-05T12:00:00"
        assert by_mac["00:11:22:33:44:55"]["last_seen_at"] == "2026-01-01T00:00:00", \
            "pre-existing last_seen_at must not be wiped"
        assert "66:77:88:99:AA:BB" in by_mac
        assert len(data) == 3, f"register must not shrink: {len(data)}"
    print("  OK: merge_register update/insert/never-shrink + preserves existing fields")


def test_merge_register_recreates_missing():
    with tempfile.TemporaryDirectory() as d:
        reg = os.path.join(d, "new-register.json")
        changed = re.merge_register([
            {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "Only-One", "last_seen_at": ""},
        ], reg)
        data = _read_json(reg)
        assert changed == 1
        assert data[0]["mac"] == "AA:BB:CC:DD:EE:FF"
        assert data[0]["hostname"] == "Only-One"
    print("  OK: merge_register recreates a missing register from rows")


def test_merge_register_empty_rows_no_change():
    with tempfile.TemporaryDirectory() as d:
        reg = os.path.join(d, "register.json")
        _write_json(reg, [{"mac": "AA:BB:CC:DD:EE:FF", "hostname": "A", "last_seen_at": ""}])
        changed = re.merge_register([], reg)
        data = _read_json(reg)
        assert changed == 0
        assert len(data) == 1
    print("  OK: merge_register with empty rows leaves register unchanged")


def test_merge_register_invalid_rows_skipped():
    with tempfile.TemporaryDirectory() as d:
        reg = os.path.join(d, "register.json")
        _write_json(reg, [{"mac": "AA:BB:CC:DD:EE:FF", "hostname": "A", "last_seen_at": ""}])
        changed = re.merge_register([
            {"mac": "not-a-mac", "hostname": "X", "last_seen_at": ""},
            {"mac": "", "hostname": "Y", "last_seen_at": ""},
        ], reg)
        data = _read_json(reg)
        assert changed == 0
        assert len(data) == 1
    print("  OK: merge_register skips invalid/empty MAC rows")


def test_last_seen_for():
    with tempfile.TemporaryDirectory() as d:
        state = os.path.join(d, "last_seen.json")
        _write_json(state, {"AA:BB:CC:DD:EE:FF": "2026-08-01T10:00:00"})
        orig = re.seen_state_path
        re.seen_state_path = lambda: state
        try:
            assert re.last_seen_for("AA:BB:CC:DD:EE:FF") == "2026-08-01T10:00:00"
            assert re.last_seen_for("00:11:22:33:44:55") is None
        finally:
            re.seen_state_path = orig
    print("  OK: last_seen_for returns timestamp / None")


def test_config_round_trip_enriched():
    with tempfile.TemporaryDirectory() as d:
        cfg = re.default_config()
        assert cfg["last_import_dir"] == "" and cfg["last_export_dir"] == ""
        cfg["macs"] = [
            {"mac": "AA:BB:CC:DD:EE:FF", "enabled": True,
             "hostname": "Host-A", "last_seen_at": "2026-08-05T12:00:00"},
        ]
        cfg["last_import_dir"] = "/tmp/imports"
        orig = re.config_path
        re.config_path = lambda: os.path.join(d, "config.json")
        try:
            assert re.save_config(cfg)
            loaded = re.load_config()
            assert loaded["macs"][0]["hostname"] == "Host-A"
            assert loaded["macs"][0]["last_seen_at"] == "2026-08-05T12:00:00"
            assert loaded["last_import_dir"] == "/tmp/imports"
            assert loaded["last_export_dir"] == ""
        finally:
            re.config_path = orig
    print("  OK: enriched config round-trip (hostname/last_seen_at/dirs)")


def test_resolve_live_register_wins_and_graceful():
    with tempfile.TemporaryDirectory() as d:
        reg = os.path.join(d, "register.json")
        _write_json(reg, [{"mac": "AA:BB:CC:DD:EE:FF", "hostname": "Known-Host"}])
        known = re.hostname_map(reg)
    orig_arp = re.mac_tools.check_arp_cache
    orig_gethost = socket.gethostbyaddr
    re.mac_tools.check_arp_cache = lambda mac="": []
    socket.gethostbyaddr = lambda ip: (_ for _ in ()).throw(socket.herror("NXDOMAIN"))
    try:
        names, last_seen = re.resolve_hostnames_live(
            ["AA:BB:CC:DD:EE:FF", "00:11:22:33:44:55"], known_map=known)
        assert names["AA:BB:CC:DD:EE:FF"] == "Known-Host", names
        assert names["00:11:22:33:44:55"] == "", "unknown MAC degrades to empty, no raise"
        assert last_seen == {}, "no ARP entries means no last_seen stamps"
    finally:
        re.mac_tools.check_arp_cache = orig_arp
        socket.gethostbyaddr = orig_gethost
    print("  OK: resolve_hostnames_live register-first + graceful fallback")


def test_resolve_live_reverse_dns_from_arp():
    orig_arp = re.mac_tools.check_arp_cache
    orig_gethost = socket.gethostbyaddr
    orig_ptr = re._ptr_via_router
    re.mac_tools.check_arp_cache = lambda mac="": [
        {"mac": "00:11:22:33:44:55", "ip": "198.51.100.10", "state": "REACHABLE"}]
    re._ptr_via_router = lambda ip: "router.home" if ip == "198.51.100.10" else ""
    socket.gethostbyaddr = lambda ip: (_ for _ in ()).throw(socket.herror("x"))
    try:
        names, last_seen = re.resolve_hostnames_live(["00:11:22:33:44:55"], known_map={})
        assert names["00:11:22:33:44:55"] == "router.home", names
        assert "00:11:22:33:44:55" in last_seen, "ARP-present MAC should get last_seen stamp"
    finally:
        re.mac_tools.check_arp_cache = orig_arp
        socket.gethostbyaddr = orig_gethost
        re._ptr_via_router = orig_ptr
    print("  OK: resolve_hostnames_live reverse-DNS from ARP cache + last_seen")


def main():
    tests = [test_hostname_map_from_file, test_hostname_map_missing_file,
             test_merge_register_update_insert_no_shrink,
             test_merge_register_recreates_missing,
             test_merge_register_empty_rows_no_change,
             test_merge_register_invalid_rows_skipped,
             test_last_seen_for, test_config_round_trip_enriched,
             test_resolve_live_register_wins_and_graceful,
             test_resolve_live_reverse_dns_from_arp]
    for t in tests:
        t()
    print("ALL LIST-ENRICHMENT TESTS PASSED")


if __name__ == "__main__":
    main()
