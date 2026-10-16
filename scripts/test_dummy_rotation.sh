#!/usr/bin/env bash
# Dummy-interface rotation + restore test for mac-changer (MUST run as root).
# Never touches a real NIC: creates/uses a synthetic `macchg0` dummy interface.
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
FISHEYE_GUI="$(cd "$DIR/../fisheye-gui" && pwd)"
cd "$DIR"

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] Run as root: sudo bash scripts/test_dummy_rotation.sh" >&2
    exit 1
fi

IFACE="macchg0"
MAC_A="02:00:00:00:00:0a"
MAC_B="02:00:00:00:00:0b"

echo "[*] Creating dummy interface $IFACE"
ip link add "$IFACE" type dummy 2>/dev/null || { echo "[!] Could not create dummy"; exit 1; }
trap 'ip link del '"$IFACE"' 2>/dev/null || true; echo "[*] Cleaned up $IFACE"' EXIT

echo "[*] Reading current MAC"
CUR=$(ip link show "$IFACE" | grep -oE 'link/ether [0-9a-f:]{17}' | awk '{print $2}')
echo "      current=$CUR"

echo "[*] Exercise mac_tools.change_mac -> $MAC_A"
python3 -c "
import sys, os
sys.path.insert(0, \"$FISHEYE_GUI\")
from lib import mac_tools
ok, msg = mac_tools.change_mac('$IFACE', '$MAC_A')
print(f'      change -> {msg}')
sys.exit(0 if ok else 1)
"
CUR_A=$(ip link show "$IFACE" | grep -oE 'link/ether [0-9a-f:]{17}' | awk '{print $2}')
echo "[*] Applied MAC: $CUR_A"

echo "[*] Exercise rotation engine helpers on dummy (no real net touched)"
python3 -c "
import sys, os
sys.path.insert(0, \"$FISHEYE_GUI\")
from src.rotation_engine import get_interface_ip, get_gateway, test_connection, dhcp_renew
print('      interface_ip:', repr(get_interface_ip('$IFACE')))
print('      gateway:     ', repr(get_gateway()))
ok, detail = test_connection('$IFACE')
print('      connectivity:', detail)
"

echo "[*] Backup original + restore"
python3 -c "
import sys, os, time
sys.path.insert(0, \"$FISHEYE_GUI\")
from lib import mac_tools
ok, mac = mac_tools.get_current_mac('$IFACE')
rid = mac_tools.backup_mac('$IFACE', mac)
print(f'      backed up original {mac} -> row {rid}')
backup = mac_tools.get_last_backup('$IFACE')
print(f'      last backup: {backup}')
ok2, msg2 = mac_tools.change_mac_restore('$IFACE')
print(f'      restore -> {msg2}')
ok3, mac3 = mac_tools.get_current_mac('$IFACE')
print(f'      restored MAC: {mac3}')
assert mac3 == mac, 'Restore mismatch'
print('      RESTORE OK')
"

echo "[*] Rotation worker smoke (2 MACs, 1s interval, stop after ~2.5s)"
python3 -c "
import sys, os, time, threading
sys.path.insert(0, \"$FISHEYE_GUI\")
from src.rotation_engine import RotationWorker
logs = []
w = RotationWorker('$IFACE', [(True, '$MAC_A'), (True, '$MAC_B')], 1,
                   log_cb=logs.append, done_cb=lambda: None)
w.start()
time.sleep(2.5)
w.stop()
time.sleep(0.5)
print('      log lines:', len(logs))
for line in logs:
    print('      ', line)
assert any('MAC changed' in l or 'change_mac' in l for l in logs), 'No change logged'
print('      WORKER OK')
"

echo "ALL DUMMY TESTS PASSED"
