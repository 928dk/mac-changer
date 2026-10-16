#!/usr/bin/env python3
"""Spec 073 engine tests: VPN-proof get_gateway, test_connection iface routing,
dhcp_renew dhclient guard + nmcli retry, reverse-DNS PTR fallback, and ARP sweep
gating (no root required, no live network — subprocess/socket mocked)."""
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

DIR = Path(__file__).resolve().parents[1]
FISHEYE_GUI = DIR.parent / "fisheye-gui"

for p in (str(FISHEYE_GUI), str(DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import rotation_engine as re

DUAL_DEFAULT = (
    "default via 198.51.100.10 dev pvpnksintrf0 proto static metric 98 \n"
    "default via 203.0.113.10 dev eno1 proto dhcp src 203.0.113.10 metric 100 \n"
)


def _cp(args, rc, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr=stderr)


def test_gateway_dual_default():
    orig = re.subprocess.run

    def fake_run(args, **kw):
        if args == ["ip", "route", "show", "default"]:
            return _cp(args, 0, DUAL_DEFAULT)
        if args == ["ip", "route", "show", "default", "dev", "eno1"]:
            return _cp(args, 0, DUAL_DEFAULT.splitlines()[1] + "\n")
        return _cp(args, 0, "")

    re.subprocess.run = fake_run
    try:
        assert re.get_gateway("eno1") == "203.0.113.10", re.get_gateway("eno1")
        assert re.get_gateway() == "198.51.100.10", re.get_gateway()
    finally:
        re.subprocess.run = orig
    print("  OK: get_gateway(eno1) -> LAN gw; get_gateway() keeps legacy first via")


def test_gateway_dual_default_lib():
    orig = re.mac_tools.subprocess.run

    def fake_run(args, **kw):
        if args == ["ip", "route", "show", "default"]:
            return _cp(args, 0, DUAL_DEFAULT)
        if args == ["ip", "route", "show", "default", "dev", "eno1"]:
            return _cp(args, 0, DUAL_DEFAULT.splitlines()[1] + "\n")
        return _cp(args, 0, "")

    re.mac_tools.subprocess.run = fake_run
    try:
        assert re.mac_tools.get_gateway("eno1") == "203.0.113.10"
        assert re.mac_tools.get_gateway() == "198.51.100.10"
    finally:
        re.mac_tools.subprocess.run = orig
    print("  OK: lib mac_tools.get_gateway matches (shared fix)")


def test_gateway_no_default_for_iface():
    orig = re.subprocess.run

    def fake_run(args, **kw):
        if args == ["ip", "route", "show", "default", "dev", "wlan0"]:
            return _cp(args, 0, "")
        return _cp(args, 0, DUAL_DEFAULT)

    re.subprocess.run = fake_run
    try:
        assert re.get_gateway("wlan0") == "", re.get_gateway("wlan0")
    finally:
        re.subprocess.run = orig
    print("  OK: get_gateway(iface) with no default route on iface -> ''")


def test_gateway_subprocess_error():
    orig = re.subprocess.run
    re.subprocess.run = lambda *a, **kw: (_ for _ in ()).throw(OSError("boom"))
    try:
        assert re.get_gateway("eno1") == ""
    finally:
        re.subprocess.run = orig
    print("  OK: get_gateway swallows subprocess errors -> ''")


def test_test_connection_passes_iface():
    orig = (re.get_gateway, re.get_interface_ip,
            re.mac_tools.ping_device, re.mac_tools.active_internet_probe)
    calls = []

    def fake_gateway(iface=None):
        calls.append(iface)
        return "203.0.113.10"

    re.get_gateway = fake_gateway
    re.get_interface_ip = lambda iface: "203.0.113.10"
    re.mac_tools.ping_device = lambda ip, timeout=2: (True, 0.004)
    re.mac_tools.active_internet_probe = lambda timeout=3: (True, "internet-ok")
    try:
        ok, detail = re.test_connection("eno1")
        assert ok, detail
        assert "gateway=203.0.113.10" in detail, detail
        assert calls == ["eno1"], calls
    finally:
        (re.get_gateway, re.get_interface_ip,
         re.mac_tools.ping_device, re.mac_tools.active_internet_probe) = orig
    print("  OK: test_connection(iface) pings the iface gateway (not first default)")


def test_dhcp_renew_dhclient_missing():
    orig_run = re.subprocess.run
    orig_which = re.shutil.which

    def fake_run(args, **kw):
        cmd = args[0]
        if cmd == "nmcli":
            return _cp(args, 1, "", "nmcli: device 'eno1' not reapply-able")
        return _cp(args, 1, "", "not reached")

    re.subprocess.run = fake_run
    re.shutil.which = lambda name: None
    try:
        ok, detail = re.dhcp_renew("eno1")
        assert ok is False
        assert "dhclient not installed" in detail, detail
    finally:
        re.subprocess.run = orig_run
        re.shutil.which = orig_which
    print("  OK: dhcp_renew with missing dhclient returns clean detail, no exception")


def test_dhcp_renew_nmcli_retry():
    orig_run = re.subprocess.run
    orig_nm = re._get_nm_connection_name
    orig_get_mac = re.mac_tools.get_current_mac
    rc_by_cmd = {}

    def fake_nm(iface):
        return "Wired connection 1"

    def fake_run(args, **kw):
        rc_by_cmd[tuple(args)] = 0
        if args[:3] == ["nmcli", "connection", "down"]:
            return _cp(args, 0, "Connection successfully deactivated")
        if args[:3] == ["nmcli", "connection", "modify"]:
            return _cp(args, 0, "")
        if args[:3] == ["nmcli", "connection", "up"]:
            return _cp(args, 1, "", "Connection activation failed")
        if args[:3] == ["nmcli", "device", "reapply"]:
            return _cp(args, 1, "", "reapply failed")
        return _cp(args, 0, "")

    re.subprocess.run = fake_run
    re._get_nm_connection_name = fake_nm
    re.mac_tools.get_current_mac = lambda iface: (True, "AA:BB:CC:DD:EE:FF")
    try:
        ok, detail = re.dhcp_renew("eno1")
        assert not ok, detail
        assert "nmcli connection up failed" in detail, detail
        assert ("nmcli", "connection", "down", "Wired connection 1") in rc_by_cmd
        assert ("nmcli", "connection", "up", "Wired connection 1") in rc_by_cmd
    finally:
        re.subprocess.run = orig_run
        re._get_nm_connection_name = orig_nm
        re.mac_tools.get_current_mac = orig_get_mac
    print("  OK: dhcp_renew tries nmcli connection down/up then reapply")


def test_ptr_fallback_via_router():
    orig_arp = re.mac_tools.check_arp_cache
    orig_gethost = socket.gethostbyaddr
    orig_run = re.subprocess.run
    orig_which = re.shutil.which

    re.mac_tools.check_arp_cache = lambda mac="": [
        {"mac": "AA:BB:CC:DD:EE:FF", "ip": "203.0.113.10", "state": "REACHABLE"}]
    socket.gethostbyaddr = lambda ip: (_ for _ in ()).throw(socket.herror("NXDOMAIN"))
    re.shutil.which = lambda name: "/usr/bin/dig" if name == "dig" else None

    def fake_run(args, **kw):
        if args[:4] == ["ip", "route", "get", "203.0.113.10"]:
            return _cp(args, 0, "203.0.113.10 dev eno1 src 203.0.113.10 uid 1000 \n")
        if args == ["ip", "route", "show", "default", "dev", "eno1"]:
            return _cp(args, 0, DUAL_DEFAULT.splitlines()[1] + "\n")
        if args[0] == "dig":
            return _cp(args, 0, "host-144.lan.\n")
        return _cp(args, 0, "")

    re.subprocess.run = fake_run
    try:
        names, _last_seen = re.resolve_hostnames_live(["AA:BB:CC:DD:EE:FF"], known_map={})
        assert names["AA:BB:CC:DD:EE:FF"] == "host-144.lan", names
    finally:
        re.mac_tools.check_arp_cache = orig_arp
        socket.gethostbyaddr = orig_gethost
        re.subprocess.run = orig_run
        re.shutil.which = orig_which
    print("  OK: PTR fallback resolves via the on-link router with dig -x")


def test_scan_registered_sweep_skipped_nonroot():
    orig = (re.os.geteuid, re._pick_sweep_interface, re.arp_sweep,
            re.load_registered, re.mac_tools.check_arp_cache,
            re.load_seen_state, re.save_seen_state)
    re.os.geteuid = lambda: 1000
    re._pick_sweep_interface = lambda: "eno1"
    re.arp_sweep = lambda iface: (_ for _ in ()).throw(RuntimeError("ARP sweep requires root"))
    re.load_registered = lambda path=None: [
        {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "Host-A"}]
    re.mac_tools.check_arp_cache = lambda mac="": []
    re.load_seen_state = lambda: {}
    re.save_seen_state = lambda state: True
    logs = []
    try:
        seen, total, results = re.scan_registered(log_cb=logs.append)
        assert seen == 0 and total == 1
        assert any("ARP sweep skipped" in l for l in logs), logs
    finally:
        (re.os.geteuid, re._pick_sweep_interface, re.arp_sweep,
         re.load_registered, re.mac_tools.check_arp_cache,
         re.load_seen_state, re.save_seen_state) = orig
    print("  OK: non-root scan catches the sweep RuntimeError and uses the passive path")


def test_scan_registered_sweep_root_invokes():
    orig = (re.os.geteuid, re._pick_sweep_interface, re.arp_sweep,
            re.load_registered, re.mac_tools.check_arp_cache,
            re.load_seen_state, re.save_seen_state)
    re.os.geteuid = lambda: 0
    re._pick_sweep_interface = lambda: "eno1"
    re.arp_sweep = lambda iface: 254
    re.load_registered = lambda path=None: [
        {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "Host-A"}]
    re.mac_tools.check_arp_cache = lambda mac="": [
        {"mac": "AA:BB:CC:DD:EE:FF", "ip": "203.0.113.10", "state": "REACHABLE"}]
    re.load_seen_state = lambda: {}
    re.save_seen_state = lambda state: True
    logs = []
    try:
        seen, total, results = re.scan_registered(log_cb=logs.append)
        assert seen == 1 and total == 1
        assert any("ARP sweep: probed 254 hosts on eno1" in l for l in logs), logs
    finally:
        (re.os.geteuid, re._pick_sweep_interface, re.arp_sweep,
         re.load_registered, re.mac_tools.check_arp_cache,
         re.load_seen_state, re.save_seen_state) = orig
    print("  OK: root scan invokes the ARP sweep and reports probed host count")


def test_arp_sweep_executes_parallel():
    orig = (re.os.geteuid, re.shutil.which, re._interface_net, re.subprocess.run)
    re.os.geteuid = lambda: 0
    re.shutil.which = lambda name: "/usr/bin/arping" if name == "arping" else None
    re._interface_net = lambda iface: ("203.0.113.10", 24)
    probed = []

    def fake_run(args, **kw):
        if args[0] == "arping":
            probed.append(args)
            return _cp(args, 0)
        return _cp(args, 0, "")

    re.subprocess.run = fake_run
    try:
        count = re.arp_sweep("eno1")
        assert count == 254, count
        assert len(probed) == 254, len(probed)
        assert all(a[2] == "eno1" for a in probed)
    finally:
        (re.os.geteuid, re.shutil.which, re._interface_net, re.subprocess.run) = orig
    print("  OK: arp_sweep probes the full /24 in parallel and returns the host count")


def main():
    tests = [test_gateway_dual_default, test_gateway_dual_default_lib,
             test_gateway_no_default_for_iface, test_gateway_subprocess_error,
             test_test_connection_passes_iface,
             test_dhcp_renew_dhclient_missing, test_dhcp_renew_nmcli_retry,
             test_ptr_fallback_via_router,
             test_scan_registered_sweep_skipped_nonroot,
             test_scan_registered_sweep_root_invokes,
             test_arp_sweep_executes_parallel]
    for t in tests:
        t()
    print("ALL VPN-CONNECTIVITY TESTS PASSED")


if __name__ == "__main__":
    main()
