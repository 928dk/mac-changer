#!/usr/bin/env python3
"""Tests for mac-changer firewall_allow detection (spec 098).

No root required: classification is tested via precomputed (ok, detail) probe
tuples; merge/set/load run against temp registers. The real-register test
reads only and asserts every entry carries a JSON bool firewall_allow.
"""
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

from src.rotation_engine import (  # noqa: E402
    detect_firewall_allow,
    firewall_map,
    set_firewall_allow,
    merge_register,
    load_registered,
)

REGISTER = DIR / "RegisteredAddresses.json"


def _write(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    return path


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# detect_firewall_allow classification
# ---------------------------------------------------------------------------

def test_classify_allowed():
    assert detect_firewall_allow("eth0", probe=(True, "ip=203.0.113.10 gateway=203.0.113.10 internet-ok")) is True
    print("  OK: connectivity ok -> True")


def test_classify_blocked():
    detail = "No response from 1.1.1.1:80 — no internet or blocked"
    assert detect_firewall_allow("eth0", probe=(False, detail)) is False
    print("  OK: gateway up + probe failed -> False")


def test_classify_indeterminate_gateway_down():
    assert detect_firewall_allow("eth0", probe=(False, "gateway 203.0.113.10 did not answer ping")) is None
    assert detect_firewall_allow("eth0", probe=(False, "no IPv4 address on interface")) is None
    assert detect_firewall_allow("eth0", probe=(False, "scapy not available")) is None
    assert detect_firewall_allow("eth0", probe=(False, "Probe error: boom")) is None
    assert detect_firewall_allow("eth0", probe=(False, "Unexpected response: <IP ...>")) is None
    print("  OK: gateway/IP/probe failures -> None (never persist)")


def test_classify_no_probe_runs_test_connection():
    # Without a probe argument, detect_firewall_allow calls test_connection.
    # Monkeypatched per-call below so the test never touches the network.
    from src import rotation_engine as eng
    orig = eng.test_connection
    eng.test_connection = lambda iface: (False, "No response from 1.1.1.1:80 — blocked")
    try:
        assert detect_firewall_allow("eth0") is False
    finally:
        eng.test_connection = orig
    print("  OK: default path reuses test_connection")


# ---------------------------------------------------------------------------
# firewall_map
# ---------------------------------------------------------------------------

def test_firewall_map_defaults_true():
    with tempfile.TemporaryDirectory() as td:
        reg = _write(os.path.join(td, "reg.json"), [
            {"mac": "AA:BB:CC:DD:EE:01", "hostname": "a"},
            {"mac": "AA:BB:CC:DD:EE:02", "hostname": "b", "firewall_allow": False},
        ])
        fm = firewall_map(reg)
        assert fm["AA:BB:CC:DD:EE:01"] is True
        assert fm["AA:BB:CC:DD:EE:02"] is False
    print("  OK: firewall_map defaults True, preserves False")


def test_firewall_map_tolerant():
    assert firewall_map("/nonexistent/no-register.json") == {}
    with tempfile.TemporaryDirectory() as td:
        reg = os.path.join(td, "bad.json")
        with open(reg, "w") as f:
            f.write("not json")
        assert firewall_map(reg) == {}
        with open(reg, "w") as f:
            f.write('{"not": "a list"}')
        assert firewall_map(reg) == {}
    print("  OK: firewall_map tolerant of missing/malformed file")


# ---------------------------------------------------------------------------
# merge_register (bool-aware)
# ---------------------------------------------------------------------------

def test_merge_preserves_false():
    with tempfile.TemporaryDirectory() as td:
        reg = _write(os.path.join(td, "reg.json"), [
            {"mac": "AA:BB:CC:DD:EE:01", "hostname": "a", "last_seen_at": "",
             "firewall_allow": True},
        ])
        merge_register([{"mac": "AA:BB:CC:DD:EE:01", "hostname": "a",
                         "last_seen_at": "", "firewall_allow": False}], reg)
        entry = _read(reg)[0]
        assert entry["firewall_allow"] is False
    print("  OK: merge writes firewall_allow False (bool-aware)")


def test_merge_no_key_keeps_existing():
    with tempfile.TemporaryDirectory() as td:
        reg = _write(os.path.join(td, "reg.json"), [
            {"mac": "AA:BB:CC:DD:EE:01", "hostname": "old", "last_seen_at": "",
             "firewall_allow": False},
        ])
        merge_register([{"mac": "AA:BB:CC:DD:EE:01", "hostname": "new"}], reg)
        entry = _read(reg)[0]
        assert entry["firewall_allow"] is False
        assert entry["hostname"] == "new"
    print("  OK: row without key does not clobber existing flag")


def test_merge_insert_defaults_true():
    with tempfile.TemporaryDirectory() as td:
        reg = _write(os.path.join(td, "reg.json"), [])
        merge_register([{"mac": "AA:BB:CC:DD:EE:01", "hostname": "a"}], reg)
        entry = _read(reg)[0]
        assert entry["firewall_allow"] is True
    print("  OK: inserted entries default firewall_allow True")


# ---------------------------------------------------------------------------
# set_firewall_allow (atomic single-field update)
# ---------------------------------------------------------------------------

def test_set_firewall_allow_single_field():
    with tempfile.TemporaryDirectory() as td:
        reg = _write(os.path.join(td, "reg.json"), [
            {"mac": "AA:BB:CC:DD:EE:01", "hostname": "a", "last_seen_at": "2026-01-01T00:00:00",
             "firewall_allow": True},
            {"mac": "AA:BB:CC:DD:EE:02", "hostname": "b", "last_seen_at": "",
             "firewall_allow": True},
        ])
        rc = set_firewall_allow("AA:BB:CC:DD:EE:01", False, reg)
        data = _read(reg)
        assert rc == 1
        assert data[0]["firewall_allow"] is False
        assert data[0]["hostname"] == "a"
        assert data[0]["last_seen_at"] == "2026-01-01T00:00:00"
        assert data[1]["firewall_allow"] is True
        assert [e["mac"] for e in data] == ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]
    print("  OK: set_firewall_allow updates one field atomically, order preserved")


def test_set_firewall_allow_case_insensitive():
    with tempfile.TemporaryDirectory() as td:
        reg = _write(os.path.join(td, "reg.json"), [
            {"mac": "AA:BB:CC:DD:EE:01", "hostname": "a", "last_seen_at": "",
             "firewall_allow": False},
        ])
        rc = set_firewall_allow("aa-bb-cc-dd-ee-01", True, reg)
        assert rc == 1
        assert _read(reg)[0]["firewall_allow"] is True
    print("  OK: set_firewall_allow normalizes MAC for lookup")


def test_set_firewall_allow_noop_unknown():
    with tempfile.TemporaryDirectory() as td:
        reg = _write(os.path.join(td, "reg.json"), [
            {"mac": "AA:BB:CC:DD:EE:01", "hostname": "a", "last_seen_at": ""},
        ])
        assert set_firewall_allow("FF:FF:FF:FF:FF:FF", True, reg) == 0
        assert set_firewall_allow("not-a-mac", True, reg) == 0
        assert len(_read(reg)) == 1
    print("  OK: unknown/invalid MAC -> no-op, register untouched")


# ---------------------------------------------------------------------------
# load_registered exposure
# ---------------------------------------------------------------------------

def test_load_registered_exposes_flag():
    with tempfile.TemporaryDirectory() as td:
        reg = _write(os.path.join(td, "reg.json"), [
            {"mac": "AA:BB:CC:DD:EE:01", "hostname": "a", "last_seen_at": ""},
            {"mac": "AA:BB:CC:DD:EE:02", "hostname": "b", "last_seen_at": "",
             "firewall_allow": False},
        ])
        devs = load_registered(reg)
        assert devs[0]["firewall_allow"] is True
        assert devs[1]["firewall_allow"] is False
    print("  OK: load_registered exposes firewall_allow (default True)")


# ---------------------------------------------------------------------------
# Real register backfill shape
# ---------------------------------------------------------------------------

def test_real_register_backfill_shape():
    if not REGISTER.is_file():
        print("  SKIP: real register not present")
        return
    if not os.access(str(REGISTER), os.R_OK):
        print(f"  SKIP: {REGISTER} not readable (root-owned)")
        return
    data = _read(REGISTER)
    assert data, "register is empty"
    for e in data:
        assert isinstance(e.get("firewall_allow"), bool), e
        assert e["firewall_allow"] is True, e
    devs = load_registered(str(REGISTER))
    assert len(devs) == len(data), (len(devs), len(data))
    assert all(d["firewall_allow"] is True for d in devs)
    print(f"  OK: real register -> {len(devs)}/{len(data)} entries firewall_allow true (bool)")


def main():
    tests = [
        test_classify_allowed,
        test_classify_blocked,
        test_classify_indeterminate_gateway_down,
        test_classify_no_probe_runs_test_connection,
        test_firewall_map_defaults_true,
        test_firewall_map_tolerant,
        test_merge_preserves_false,
        test_merge_no_key_keeps_existing,
        test_merge_insert_defaults_true,
        test_set_firewall_allow_single_field,
        test_set_firewall_allow_case_insensitive,
        test_set_firewall_allow_noop_unknown,
        test_load_registered_exposes_flag,
        test_real_register_backfill_shape,
    ]
    for t in tests:
        t()
    print("ALL FIREWALL-ALLOW TESTS PASSED")


if __name__ == "__main__":
    main()
