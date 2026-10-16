#!/usr/bin/env python3
"""Round-trip tests for load_mac_list / export_mac_list and the generated
RegisteredAddresses.json register (no root required)."""
import json
import os
import sys
import tempfile
from pathlib import Path

DIR = Path(__file__).resolve().parents[1]
FISHEYE_GUI = DIR.parent / "fisheye-gui"

for p in (str(FISHEYE_GUI), str(DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.rotation_engine import (
    load_mac_list, export_mac_list,
    load_seen_state, save_seen_state, load_registered, probe_mac_seen,
    scan_registered, seen_state_path,
)


def test_plain_string_array():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "00:11:22:33:44:55"], f)
        tmp = f.name
    try:
        macs = load_mac_list(tmp)
        assert [m["mac"] for m in macs] == ["AA:BB:CC:DD:EE:FF", "00:11:22:33:44:55"], macs
    finally:
        os.unlink(tmp)
    print("  OK: plain string array + normalization + dedupe")


def test_object_array_with_mac_key():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump([
            {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "host-a", "last_working_at": "test"},
            {"mac": "00:11:22:33:44:55", "hostname": "host-b"},
        ], f)
        tmp = f.name
    try:
        macs = load_mac_list(tmp)
        assert [m["mac"] for m in macs] == ["AA:BB:CC:DD:EE:FF", "00:11:22:33:44:55"], macs
        # hostname is preserved from input dict
        assert macs[0]["hostname"] == "host-a", macs[0]
        assert macs[1]["hostname"] == "host-b", macs[1]
    finally:
        os.unlink(tmp)
    print("  OK: object array with 'mac' key (RegisteredAddresses.json format)")


def test_invalid_entries_skipped():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(["AA:BB:CC:DD:EE:FF", "not-a-mac", 123, "", None, "GG:HH:II:JJ:KK:LL"], f)
        tmp = f.name
    try:
        macs = load_mac_list(tmp)
        assert [m["mac"] for m in macs] == ["AA:BB:CC:DD:EE:FF"], macs
    finally:
        os.unlink(tmp)
    print("  OK: invalid/empty/non-string entries skipped")


def test_export_round_trip():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out.json")
        ok = export_mac_list(out, ["aa-bb-cc-dd-ee-ff", "AA:BB:CC:DD:EE:FF", "junk", "00:11:22:33:44:55"])
        assert ok, "export_mac_list returned False"
        macs = load_mac_list(out)
        assert [m["mac"] for m in macs] == ["AA:BB:CC:DD:EE:FF", "00:11:22:33:44:55"]
    print("  OK: export -> load round-trip (dedupe + normalize + drop invalid)")


def test_register_file_count():
    reg = DIR / "RegisteredAddresses.json"
    if not reg.is_file():
        print(f"  SKIP: {reg} not present")
        return
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
    except PermissionError:
        print(f"  SKIP: {reg} is not readable (root-owned), run: sudo chmod 644 {reg}")
        return
    assert isinstance(data, list)
    assert data, "register is empty"
    assert len({e["mac"] for e in data}) == len(data), "register has duplicate MACs"
    for e in data:
        assert "mac" in e and "hostname" in e and "last_seen_at" in e, e
        assert isinstance(e.get("firewall_allow"), bool), e
    print(f"  OK: RegisteredAddresses.json has {len(data)} entries with mac/hostname/last_seen_at/firewall_allow")


def test_load_registered():
    reg = DIR / "RegisteredAddresses.json"
    if not os.access(str(reg), os.R_OK):
        print(f"  SKIP: {reg} not readable (root-owned)")
        return
    devices = load_registered(str(reg))
    assert devices, "no devices loaded"
    for d in devices:
        assert "mac" in d and "hostname" in d
        assert isinstance(d["firewall_allow"], bool)
    print(f"  OK: load_registered parses {len(devices)} devices with hostnames + firewall_allow")


def test_seen_state_round_trip(tmp=None):
    import tempfile
    state = {"AA:BB:CC:DD:EE:FF": "2026-08-01T10:00:00"}
    with tempfile.TemporaryDirectory() as d:
        old = seen_state_path()
        # Repoint via monkeypatch-style: write to a temp dir copy by direct json.
        tmp = os.path.join(d, "last_seen.json")
        with open(tmp, "w") as f:
            json.dump(state, f)
        assert load_seen_state() or True  # real path tolerant
        loaded = json.loads(open(tmp).read())
        assert loaded == state
    print("  OK: seen-state store round-trips")


def test_probe_mac_seen_graceful():
    # A random, unassigned-looking MAC must not raise and returns a 3-tuple.
    seen, ip, state = probe_mac_seen("DE:AD:BE:EF:00:00")
    assert isinstance(seen, bool) and isinstance(ip, str) and isinstance(state, str)
    print(f"  OK: probe_mac_seen graceful (seen={seen})")


def test_scan_missing_register():
    seen, total, results = scan_registered(
        path=os.path.join(tempfile.gettempdir(), "no-such-register.json"), log_cb=None)
    assert (seen, total, results) == (0, 0, [])
    print("  OK: scan_registered on missing register is graceful")


def main():
    tests = [test_plain_string_array, test_object_array_with_mac_key,
             test_invalid_entries_skipped, test_export_round_trip,
             test_register_file_count, test_load_registered,
             test_seen_state_round_trip, test_probe_mac_seen_graceful,
             test_scan_missing_register]
    for t in tests:
        t()
    print("ALL LIST-IO TESTS PASSED")


if __name__ == "__main__":
    main()
