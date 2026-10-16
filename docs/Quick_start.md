# Quick Start

## 1. Run
```bash
cd ~/projects/Client/mac-changer
./gui.sh
```
`gui.sh` creates `.venv`, installs `customtkinter` + `scapy` if missing, and re-launches
itself as root via `pkexec` (falls back to `sudo`). A root password prompt may appear.

## 2. First Rotation
1. **Interface**: select your network interface from the dropdown (e.g. `wlan0`).
2. **MAC list**: add MAC addresses you want to cycle (valid format `AA:BB:CC:DD:EE:FF`).
   Tick the checkbox next to each enabled entry. Each registered row also has a **FW**
   checkbox — ticked means the device is allowed through the firewall; the app auto-detects
   this during rotation and you can override it (saved via "Save list").
3. **Interval**: choose how long to hold each MAC (e.g. `30 min`).
4. Click **Start**.
   - First switch records your original MAC.
   - Each switch: apply MAC → renew DHCP → test IP + gateway + internet.
   - If a MAC fails connectivity, it is logged and the next enabled MAC is tried.
5. Click **Stop** to stop rotating; **Restore original** to return to your backed-up MAC.

## 3. What You Should See
- Log pane streams `[ok] MAC changed to …`, `[ok] DHCP renewed`, `[ok] internet reachable`.
- On failure you see the reason and automatic advance to the next MAC.

## 4. Reset
Delete `~/.config/mac-changer/config.json` to restore default settings.

> **Testing note**: never rotate your real NIC during development — use
> `scripts/test_dummy_rotation.sh` (creates a `macchg0` dummy interface) instead.
