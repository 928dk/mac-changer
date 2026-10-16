#!/usr/bin/env python3
"""Tests for mac-changer hostname anonymization (spec 097).

No root required: blank path is pure; the scan path monkeypatches the live
resolver. The real-register classification test reads only.
"""
import importlib.util
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

from src.rotation_engine import blank_hostnames, is_valid_hostname  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "anonymize_hostnames", DIR / "scripts" / "anonymize_hostnames.py")
anonymize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(anonymize)

REGISTER = DIR / "RegisteredAddresses.json"


def test_valid_hostnames():
    for ok in ("Cardterminal", "Support-PC", "host-a", "myhost.local",
               "a", "fqdn.example.com."):
        assert is_valid_hostname(ok), ok
    print("  OK: valid hostnames accepted")


def test_invalid_hostnames():
    for bad in ("", "2.EXAMPLE 00000000 Asset Tag TLF", "NUC 1", "SONY PS 5",
                "Card Terminal", "host name", "café", "-lead", "trail-",
                "a..b", "label-" * 40 + "x", "x" * 64, "a." + "b" * 254):
        assert not is_valid_hostname(bad), repr(bad)
    print("  OK: free-text labels / malformed hostnames rejected")


def test_blank_deterministic_and_unique():
    devices = [
        {"mac": "AA:BB:CC:DD:EE:01", "hostname": "2.EXAMPLE 00000000 Asset Tag TLF"},
        {"mac": "AA:BB:CC:DD:EE:02", "hostname": "NUC 1"},
        {"mac": "AA:BB:CC:DD:EE:03", "hostname": "Cardterminal"},
        {"mac": "AA:BB:CC:DD:EE:04", "hostname": "SONY PS 5"},
    ]
    out1, blanks1 = blank_hostnames([dict(d) for d in devices], anonymize.DEFAULT_WORDLIST)
    out2, blanks2 = blank_hostnames([dict(d) for d in devices], anonymize.DEFAULT_WORDLIST)
    assert out1 == out2 and blanks1 == blanks2
    new_names = [d["hostname"] for d in out1]
    assert len(set(new_names)) == len(new_names), new_names
    assert "Cardterminal" in new_names
    assert len(blanks1) == 3
    assert {b["new"] for b in blanks1} <= set(anonymize.DEFAULT_WORDLIST)
    print("  OK: deterministic, unique, valid hostname kept")


def test_blank_wordlist_too_small():
    devices = [
        {"mac": "AA:BB:CC:DD:EE:0%d" % i, "hostname": "device %d" % i}
        for i in range(1, 5)
    ]
    try:
        blank_hostnames(devices, ["oak"])
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    print("  OK: wordlist-too-small raises ValueError")


def test_real_register_classification():
    if not REGISTER.is_file():
        print("  SKIP: real register not present")
        return
    if not os.access(str(REGISTER), os.R_OK):
        print(f"  SKIP: {REGISTER} not readable (root-owned)")
        return
    devices = anonymize.load_register(str(REGISTER))
    out, blanks = blank_hostnames(devices, anonymize.DEFAULT_WORDLIST)
    assert len(blanks) == 0, len(blanks)
    names = [d["hostname"] for d in devices]
    assert names and all(is_valid_hostname(n) for n in names)
    assert len(out) == len(devices)
    for i, d in enumerate(out):
        assert d["mac"] == devices[i]["mac"]
        assert d.get("last_seen_at") == devices[i].get("last_seen_at")
        assert d.get("firewall_allow") == devices[i].get("firewall_allow")
    print("  OK: real register -> 0 blanks (already anonymized), kept names present, order/fields preserved")


def test_blank_round_trip_no_loss_and_idempotent():
    devices = [
        {"mac": "AA:BB:CC:DD:EE:01", "hostname": "device one", "last_seen_at": "2026-01-01T00:00:00",
         "firewall_allow": True},
        {"mac": "AA:BB:CC:DD:EE:02", "hostname": "Cardterminal", "last_seen_at": "",
         "firewall_allow": False},
        {"mac": "AA:BB:CC:DD:EE:03", "hostname": "device three", "last_seen_at": "2026-01-02T00:00:00",
         "firewall_allow": True},
    ]
    out1, _ = blank_hostnames([dict(d) for d in devices], anonymize.DEFAULT_WORDLIST)
    out2, blanks2 = blank_hostnames([dict(d) for d in out1], anonymize.DEFAULT_WORDLIST)
    assert out1 == out2
    assert blanks2 == []
    for d in out1:
        assert "mac" in d and "hostname" in d and "last_seen_at" in d
        assert "firewall_allow" in d
    assert out1[0]["last_seen_at"] == "2026-01-01T00:00:00"
    assert out1[2]["last_seen_at"] == "2026-01-02T00:00:00"
    assert out1[1]["firewall_allow"] is False
    assert out1[0]["firewall_allow"] is True and out1[2]["firewall_allow"] is True
    print("  OK: round-trip no-loss, idempotent, extra fields preserved")


def _run_scan(devices, wordlist, live_map, dry_run=False):
    orig = anonymize.resolve_hostnames_live
    anonymize.resolve_hostnames_live = lambda macs, known_map=None, timeout=3, dhcp_hostnames=None: (
        {m: live_map.get(m, "") for m in macs}, {})
    try:
        return anonymize.run_scan(devices, wordlist, dry_run)
    finally:
        anonymize.resolve_hostnames_live = orig


def test_scan_placeholders_only():
    devices = [
        {"mac": "AA:BB:CC:DD:EE:01", "hostname": "elm"},
        {"mac": "AA:BB:CC:DD:EE:02", "hostname": "Cardterminal"},
        {"mac": "AA:BB:CC:DD:EE:03", "hostname": "notaword"},
        {"mac": "AA:BB:CC:DD:EE:04", "hostname": "oak"},
    ]
    live = {
        "AA:BB:CC:DD:EE:01": "office-pc",
        "AA:BB:CC:DD:EE:02": "terminal-7",
        "AA:BB:CC:DD:EE:03": "otherhost",
        "AA:BB:CC:DD:EE:04": "invalid host name",
    }
    changes, out = _run_scan(devices, ["elm", "oak"], live)
    assert len(changes) == 1, changes
    assert out[0]["hostname"] == "office-pc"
    assert out[1]["hostname"] == "Cardterminal"
    assert out[2]["hostname"] == "notaword"
    assert out[3]["hostname"] == "oak"
    print("  OK: scan replaces placeholders only; valid/real/invalid-live untouched")


def test_scan_dry_run_writes_nothing():
    devices = [{"mac": "AA:BB:CC:DD:EE:01", "hostname": "elm"}]
    changes, out = _run_scan(devices, ["elm"], {"AA:BB:CC:DD:EE:01": "office-pc"}, dry_run=True)
    assert len(changes) == 1 and out is None
    print("  OK: scan --dry-run reports without writing")


def test_atomic_write_backup_and_replace():
    with tempfile.TemporaryDirectory() as td:
        target = os.path.join(td, "reg.json")
        with open(target, "w", encoding="utf-8") as f:
            json.dump([{"mac": "AA:BB:CC:DD:EE:01", "hostname": "old"}], f)
        bak = anonymize.atomic_write([{"mac": "AA:BB:CC:DD:EE:01", "hostname": "new"}], target)
        assert bak and os.path.isfile(bak)
        with open(target, "r", encoding="utf-8") as f:
            assert json.load(f)[0]["hostname"] == "new"
        with open(bak, "r", encoding="utf-8") as f:
            assert json.load(f)[0]["hostname"] == "old"
        print("  OK: atomic_write backs up and replaces")


if __name__ == "__main__":
    test_valid_hostnames()
    test_invalid_hostnames()
    test_blank_deterministic_and_unique()
    test_blank_wordlist_too_small()
    test_real_register_classification()
    test_blank_round_trip_no_loss_and_idempotent()
    test_scan_placeholders_only()
    test_scan_dry_run_writes_nothing()
    test_atomic_write_backup_and_replace()
    print("ALL ANONYMIZE TESTS PASSED")
