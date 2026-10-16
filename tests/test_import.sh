#!/usr/bin/env bash
# Syntax + import verification for mac-changer (no root required).
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
FISHEYE_GUI="$(cd "$DIR/../fisheye-gui" && pwd)"
cd "$DIR"

echo "[1/7] py_compile src/mac_changer.py"
python3 -m py_compile src/mac_changer.py
echo "      OK"

echo "[2/7] import chain (mac_tools reuse via sys.path + app modules)"
python3 -c "
import sys, os
sys.path.insert(0, '$FISHEYE_GUI')
from lib import mac_tools
from src.rotation_engine import (
    get_interface_ip, get_gateway, dhcp_renew, test_connection,
    load_config, save_config, default_config,
    load_mac_list, export_mac_list,
    load_registered, probe_mac_seen, scan_registered, discover_devices,
    load_seen_state, save_seen_state, seen_state_path,
    load_original_hostname, save_original_hostname,
    hostname_map, firewall_map, resolve_hostnames_live, last_seen_for,
    merge_register, set_firewall_allow, detect_firewall_allow,
    is_valid_hostname, blank_hostnames,
    RotationWorker, INTERVALS, __version__,
)
print('      OK: mac_tools + rotation_engine imported')
"

echo "[3/7] list I/O round-trip tests"
python3 tests/test_list_io.py

echo "[4/7] spec 070 list-enrichment engine tests"
python3 tests/test_list_enrichment.py

echo "[5/7] spec 097 hostname anonymization tests"
python3 tests/test_anonymize_hostnames.py

echo "[6/7] spec 098 firewall_allow detection tests"
python3 tests/test_firewall_allow.py

echo "[7/7] VPN connectivity / gateway / dhcp_renew tests"
python3 tests/test_vpn_connectivity.py
echo "ALL CHECKS PASSED"
