#!/usr/bin/env python3
"""mac-changer rotation engine.

GUI-independent core: interval rotation worker, connectivity helpers, and JSON
config. No GUI dependencies so it can be exercised under root (or headless)
without customtkinter.

Reuses the fisheye-gui MAC library (`lib/mac_tools.py`) via sys.path — that
library and the parent app are never modified.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def _invoking_home() -> str:
    """Return the invoking user's home even when running as root via pkexec/sudo."""
    for env_name in ("PKEXEC_UID", "SUDO_UID"):
        raw = os.environ.get(env_name)
        if raw and os.geteuid() == 0:
            try:
                import pwd
                return pwd.getpwuid(int(raw)).pw_dir
            except Exception:
                pass
    return os.path.expanduser("~")


FISHEYE_GUI_ROOT = os.path.join(_invoking_home(), "projects", "Client", "fisheye-gui")
if not os.path.isdir(FISHEYE_GUI_ROOT):
    print(f"[-] fisheye-gui library not found at {FISHEYE_GUI_ROOT}", file=sys.stderr)
    sys.exit(1)
if FISHEYE_GUI_ROOT not in sys.path:
    sys.path.insert(0, FISHEYE_GUI_ROOT)
from lib import mac_tools  # noqa: E402


APP_NAME = "mac-changer"
__version__ = "0.8.0"

INTERVALS = [
    ("5 min", 300),
    ("15 min", 900),
    ("30 min", 1800),
    ("1 hour", 3600),
    ("2 hours", 7200),
    ("6 hours", 21600),
    ("12 hours", 43200),
    ("24 hours", 86400),
    ("custom", 0),
]
DEFAULT_INTERVAL = 1800


def config_path() -> str:
    return os.path.join(_invoking_home(), ".config", APP_NAME, "config.json")


def get_loaded_macs(cfg: dict = None) -> list:
    """Return the in-memory MAC list from config as ``[{mac, enabled}]``.

    Each entry is normalized and validated.  Invalid or duplicate MACs are
    dropped.  This is the authoritative view of what the rotation engine
    will actually use — the GUI or any headless caller should display this
    instead of raw config dumps.
    """
    if cfg is None:
        cfg = load_config()
    seen = set()
    loaded = []
    for entry in cfg.get("macs", []):
        if isinstance(entry, dict):
            raw = entry.get("mac", "")
            enabled = bool(entry.get("enabled", True))
        elif isinstance(entry, str):
            raw = entry
            enabled = True
        else:
            continue
        mac = mac_tools.normalize_mac(raw)
        if mac_tools.is_valid_mac(mac) and mac not in seen:
            seen.add(mac)
            loaded.append({"mac": mac, "enabled": enabled})
    return loaded


def loaded_macs_summary(cfg: dict = None) -> str:
    """Human-readable one-line summary of the loaded MAC list.

    Example: ``"4 MACs loaded (3 enabled, 1 disabled)"`` or ``"No MACs loaded"``.
    """
    loaded = get_loaded_macs(cfg)
    if not loaded:
        return "No MACs loaded"
    enabled = sum(1 for m in loaded if m["enabled"])
    disabled = len(loaded) - enabled
    parts = [f"{len(loaded)} MACs loaded"]
    if disabled:
        parts.append(f"({enabled} enabled, {disabled} disabled)")
    else:
        parts.append(f"({enabled} enabled)")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def get_interface_ip(iface: str) -> str:
    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show", iface],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "inet " in line:
                ip = line.split("inet ")[1].split("/")[0].strip()
                if ip and not ip.startswith("127."):
                    return ip
        return ""
    except (subprocess.SubprocessError, OSError):
        return ""


def get_gateway(iface: str = None) -> str:
    """Return the gateway for an interface, or the first global default via.

    With ``iface`` set, only that interface's default routes are considered
    (``ip route show default dev <iface>``), which excludes VPN tunnels bound
    to other interfaces (e.g. ProtonVPN's kill-switch route). Without an
    interface the legacy first-``via`` of the global default table is kept for
    backward compatibility. Returns "" when nothing is found.
    """
    argv = ["ip", "route", "show", "default"]
    if iface:
        argv += ["dev", iface]
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts and parts[0] == "default":
                if "via" in parts:
                    return parts[parts.index("via") + 1]
                return ""
        return ""
    except (subprocess.SubprocessError, OSError):
        return ""


def _get_nm_connection_name(iface: str) -> str:
    """Return the NetworkManager connection name for *iface*, or "" if not found."""
    try:
        r = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show"],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == iface:
                return parts[0]
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


def dhcp_renew(iface: str):
    """Renew DHCP after a MAC change.

    Strategy (NetworkManager):
      1. ``nmcli connection down/up`` — fully tears down and re-establishes the
         connection with a fresh DHCP request.  Before bringing the connection
         back up, the NM connection's ``cloned-mac-address`` is updated to
         match the new hardware MAC so that ``connection up`` succeeds even
         when the profile had a different MAC hardcoded.
      2. ``nmcli device reapply`` — works for minor changes (e.g. IP
         settings) but may not trigger a new DHCP cycle after a MAC swap.
      3. ``dhclient`` — fallback for non-NM setups (e.g. dhcpcd systems).

    Returns ``(ok, detail)``.
    """
    conn = _get_nm_connection_name(iface)
    if conn:
        # --- Method 1: connection down/up (best for post-MAC-change) --------
        try:
            r = subprocess.run(
                ["nmcli", "connection", "down", conn],
                capture_output=True, text=True, timeout=25
            )
            if r.returncode == 0:
                # Update cloned-mac-address to match the new hardware MAC
                # so that connection up succeeds even when the profile had
                # a different MAC hardcoded.
                ok, hw_mac = mac_tools.get_current_mac(iface)
                if ok and hw_mac:
                    hw_mac = mac_tools.normalize_mac(hw_mac)
                    subprocess.run(
                        ["nmcli", "connection", "modify", conn,
                         "802-3-ethernet.cloned-mac-address", hw_mac],
                        capture_output=True, text=True, timeout=10
                    )

                r = subprocess.run(
                    ["nmcli", "connection", "up", conn],
                    capture_output=True, text=True, timeout=35
                )
                if r.returncode == 0:
                    return True, f"DHCP renewed (nmcli {conn} down/up)"
                # Log the error for debugging
                stderr = r.stderr.strip() if r.stderr else ""
                return False, f"nmcli connection up failed: {stderr or r.stdout.strip()}"
        except (subprocess.SubprocessError, OSError):
            pass

        # --- Method 2: device reapply (minor changes) ----------------------
        try:
            r = subprocess.run(
                ["nmcli", "device", "reapply", iface],
                capture_output=True, text=True, timeout=25
            )
            if r.returncode == 0:
                return True, "DHCP renewed (nmcli device reapply)"
        except (subprocess.SubprocessError, OSError):
            pass

    # --- Method 3: dhclient (non-NM fallback) ------------------------------
    if shutil.which("dhclient") is None:
        return False, "dhclient not installed and NetworkManager unavailable"

    try:
        subprocess.run(["dhclient", "-r", iface],
                       capture_output=True, text=True, timeout=15)
    except (subprocess.SubprocessError, OSError):
        pass
    try:
        r = subprocess.run(["dhclient", iface],
                           capture_output=True, text=True, timeout=35)
        if r.returncode == 0:
            return True, "DHCP renewed (dhclient)"
        return False, f"dhclient exit {r.returncode}"
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"dhcp renew failed: {e}"


def test_connection(iface: str):
    """Verify IPv4 up + gateway ping + internet probe. Returns (ok, detail)."""
    ip = get_interface_ip(iface)
    if not ip:
        return False, "no IPv4 address on interface"
    gw = get_gateway(iface)
    if gw:
        ok, _ = mac_tools.ping_device(gw, timeout=2)
        if not ok:
            return False, f"gateway {gw} did not answer ping"
    ok, detail = mac_tools.active_internet_probe(timeout=3)
    if not ok:
        return False, detail
    return True, f"ip={ip} gateway={gw or '(none)'} internet-ok"


def detect_firewall_allow(iface: str, probe: tuple = None):
    """Classify whether the current MAC is allowed through the firewall.

    ``probe`` is an optional ``(ok, detail)`` tuple from :func:`test_connection`
    so callers (e.g. RotationWorker) can reuse a probe they already ran; when
    omitted one is performed here. Returns:
      - True  when connectivity is ok (device is allowed out).
      - False when the gateway answers but the internet probe is blocked
        ("No response from 1.1.1.1:80") — the device is firewalled.
      - None  for indeterminate cases (no IPv4, gateway down, probe
        unavailable or errored) — callers must NOT persist a change.
    """
    ok, detail = probe if probe is not None else test_connection(iface)
    if ok:
        return True
    if isinstance(detail, str) and detail.startswith("No response from 1.1.1.1:80"):
        return False
    return None


# ---------------------------------------------------------------------------
# Hostname helpers
# ---------------------------------------------------------------------------

def get_hostname() -> str:
    """Return the current system hostname."""
    try:
        r = subprocess.run(
            ["hostnamectl", "--static"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    try:
        with open("/etc/hostname", "r") as f:
            return f.read().strip()
    except OSError:
        pass
    return os.uname().nodename


def set_hostname(name: str) -> tuple:
    """Set the system hostname. Returns ``(ok, detail)``.

    Uses ``hostnamectl set-hostname`` (preferred) or writes ``/etc/hostname``
    directly. Requires root.
    """
    if not name or not name.strip():
        return False, "empty hostname"
    name = name.strip()
    if os.geteuid() != 0:
        return False, "requires root"
    try:
        r = subprocess.run(
            ["hostnamectl", "set-hostname", name],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return True, f"hostname set to {name}"
        return False, f"hostnamectl failed: {r.stderr.strip()}"
    except (subprocess.SubprocessError, OSError) as e:
        pass
    try:
        with open("/etc/hostname", "w") as f:
            f.write(name + "\n")
        return True, f"hostname written to /etc/hostname: {name}"
    except OSError as e:
        return False, f"failed to write /etc/hostname: {e}"


def restart_mdns() -> tuple:
    """Restart mDNS/Avahi if installed. Returns ``(ok, detail)``.

    No-op (returns True) when Avahi is not installed.
    """
    if shutil.which("avahi-daemon") is None:
        return True, "avahi-daemon not installed (skipped)"
    try:
        r = subprocess.run(
            ["systemctl", "restart", "avahi-daemon"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return True, "avahi-daemon restarted"
        return False, f"avahi-daemon restart failed: {r.stderr.strip()}"
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"avahi-daemon restart error: {e}"


def generate_hostname(pattern: str, mac: str) -> str:
    """Fill a hostname template with MAC-derived values.

    Supported placeholders:
      - ``{mac}`` — full normalized MAC (AA:BB:CC:DD:EE:FF)
      - ``{mac_suffix}`` — last 4 hex chars (e.g. "EEFF")
      - ``{mac_hex}`` — full MAC without colons (AABBCCDDEEFF)
      - ``{counter}`` — not filled here; caller may substitute

    Returns the filled string. Unknown placeholders are left as-is.
    """
    mac = mac_tools.normalize_mac(mac)
    mac_no_colon = mac.replace(":", "")
    mac_suffix = mac_no_colon[-4:] if len(mac_no_colon) >= 4 else mac_no_colon
    return (pattern
            .replace("{mac}", mac)
            .replace("{mac_suffix}", mac_suffix)
            .replace("{mac_hex}", mac_no_colon))


def change_mac_delayed(iface: str, new_mac: str, down_delay: int = 0,
                       sleep_cb=None) -> tuple:
    """Change an interface MAC with an optional pause between link-down and link-up.

    Mirrors ``mac_tools.change_mac`` (same command sequence, error strings, and
    return shape) but keeps the interface down for ``down_delay`` seconds before
    setting the new address and bringing the link back up. With ``down_delay=0``
    the behavior is identical to ``mac_tools.change_mac``.

    ``sleep_cb`` may be supplied to make the pause interruptible (e.g. an
    ``Event.wait``); it receives the delay in seconds. Defaults to ``time.sleep``.
    """
    mac = mac_tools.normalize_mac(new_mac)
    if not mac_tools.is_valid_mac(mac):
        return False, f"Invalid MAC address: {new_mac}"
    delay = max(int(down_delay), 0)
    sleeper = sleep_cb if sleep_cb is not None else time.sleep
    try:
        result = subprocess.run(
            ["ip", "link", "set", iface, "down"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return False, f"Failed to bring {iface} down: {result.stderr.strip()}"

        if delay:
            sleeper(delay)

        result = subprocess.run(
            ["ip", "link", "set", iface, "address", mac],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            subprocess.run(["ip", "link", "set", iface, "up"],
                           capture_output=True, timeout=5)
            return False, f"Failed to set MAC: {result.stderr.strip()}"

        result = subprocess.run(
            ["ip", "link", "set", iface, "up"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return False, f"Failed to bring {iface} up: {result.stderr.strip()}"

        ok, current = mac_tools.get_current_mac(iface)
        if ok and mac_tools.normalize_mac(current) == mac:
            return True, f"MAC changed to {mac}"
        else:
            return True, f"MAC set attempted, but verify with: ip link show {iface}"

    except subprocess.TimeoutExpired:
        return False, "Timeout running ip link commands"
    except FileNotFoundError:
        return False, "ip command not found (not Linux?)"
    except PermissionError:
        return False, "Permission denied — run as root"
    except OSError as e:
        return False, f"OS error: {e}"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def default_config() -> dict:
    return {
        "interface": "",
        "macs": [],
        "interval_seconds": DEFAULT_INTERVAL,
        "interval_label": "30 min",
        "down_delay_seconds": 0,
        "last_import_dir": "",
        "last_export_dir": "",
        "hostname_enabled": False,
        "hostname_pattern": "device-{mac_suffix}",
        "window_geometry": "760x640",
        "column_widths": {"rotate": 36, "mac": 200, "hostname": 180,
                          "last_seen": 150, "fw": 36, "remove": 36},
        "dhcp_hostnames_enabled": True,
    }


def load_config() -> dict:
    cfg = default_config()
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in cfg:
                if key in data:
                    cfg[key] = data[key]
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    if not isinstance(cfg.get("macs"), list):
        cfg["macs"] = []
    try:
        cfg["down_delay_seconds"] = max(int(cfg["down_delay_seconds"]), 0)
    except (TypeError, ValueError):
        cfg["down_delay_seconds"] = 0
    return cfg


def save_config(cfg: dict) -> bool:
    try:
        path = Path(config_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except OSError as e:
        print(f"[-] Failed to save config: {e}", file=sys.stderr)
        return False


def setup_file_logger():
    """Configure a weekly-rotating file logger for mac-changer.

    Writes to ``logs/mac-changer.log`` under the project root.  Keeps 4
    weeks of history.  Returns the logger instance.
    """
    import logging
    from logging.handlers import TimedRotatingFileHandler

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(project, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "mac-changer.log")

    logger = logging.getLogger("mac-changer")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = TimedRotatingFileHandler(
        log_path, when="W0", interval=1, backupCount=4, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    return logger


# ---------------------------------------------------------------------------
# MAC list import/export
# ---------------------------------------------------------------------------

def load_mac_list(path: str) -> list:
    """Load MACs from a JSON list file.

    Accepts a plain array of MAC strings or an array of objects with a "mac"
    key (e.g. RegisteredAddresses.json). Entries are normalized, deduplicated,
    and invalid values are skipped. Returns a list of dicts with "mac" key
    and optional "hostname", "firewall_allow" keys when present in the source.
    """
    macs = []
    seen = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[-] Failed to load MAC list {path}: {e}", file=sys.stderr)
        return macs
    if not isinstance(data, list):
        print(f"[-] MAC list {path} is not a JSON array", file=sys.stderr)
        return macs
    for entry in data:
        if isinstance(entry, dict):
            raw = entry.get("mac", "")
            hostname = str(entry.get("hostname", "") or "").strip()
            fw = entry.get("firewall_allow")
        elif isinstance(entry, str):
            raw = entry
            hostname = ""
            fw = None
        else:
            continue
        mac = mac_tools.normalize_mac(raw)
        if mac_tools.is_valid_mac(mac) and mac not in seen:
            seen.add(mac)
            item = {"mac": mac}
            if hostname:
                item["hostname"] = hostname
            if fw is not None:
                item["firewall_allow"] = bool(fw)
            macs.append(item)
    return macs


def export_mac_list(path: str, macs) -> bool:
    """Write MAC strings to a JSON array file (round-trips with load_mac_list).

    Normalizes, deduplicates, and drops invalid entries before writing.
    """
    clean = []
    seen = set()
    for item in macs:
        mac = item["mac"] if isinstance(item, dict) else item
        mac = mac_tools.normalize_mac(mac)
        if mac_tools.is_valid_mac(mac) and mac not in seen:
            seen.add(mac)
            clean.append(mac)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
            f.write("\n")
        return True
    except OSError as e:
        print(f"[-] Failed to save MAC list {path}: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Registered devices + last-seen detection
# ---------------------------------------------------------------------------

def registered_path() -> str:
    """Path to the generated registered-devices list (project root)."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project, "RegisteredAddresses.json")


def seen_state_path() -> str:
    """Path to the runtime last-seen store (kept separate from the generated register)."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project, "data", "last_seen.json")


def dhcp_hostnames_path() -> str:
    """Path to the DHCP hostname cache (MAC→hostname from captured DHCP traffic)."""
    return os.path.join(_invoking_home(), ".config", APP_NAME, "dhcp_hostnames.json")


def load_dhcp_hostnames() -> dict:
    """Return {normalized_mac: hostname} from the DHCP cache. Tolerant of missing file."""
    try:
        with open(dhcp_hostnames_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {mac_tools.normalize_mac(k): str(v)
                    for k, v in data.items()
                    if mac_tools.is_valid_mac(mac_tools.normalize_mac(k)) and v}
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {}


def save_dhcp_hostnames(mac: str, hostname: str) -> bool:
    """Persist a single MAC→hostname entry to the DHCP cache. Atomic write."""
    mac = mac_tools.normalize_mac(mac)
    if not mac_tools.is_valid_mac(mac) or not hostname:
        return False
    path = Path(dhcp_hostnames_path())
    try:
        existing = load_dhcp_hostnames()
    except Exception:
        existing = {}
    existing[mac] = hostname
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o644)
            except OSError:
                pass
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# DHCP hostname sniffer (passive, scapy-based)
# ---------------------------------------------------------------------------

def start_dhcp_sniffer(interfaces: list, log_cb=None) -> threading.Thread:
    """Start a daemon thread that passively captures DHCP option-12 hostnames.

    Listens on each interface in *interfaces* for DHCPDISCOVER/DHCPREQUEST
    packets, extracts the hostname (option 12) and client MAC (BOOTP chaddr),
    and persists new entries to ``dhcp_hostnames.json``.  Returns the thread
    (caller need not join it).  Never raises — if scapy is missing the thread
    exits silently.
    """
    try:
        from scapy.layers.inet import IP, UDP
        from scapy.layers.l2 import Ether
        from scapy.layers.dhcp import DHCP, BOOTP
        from scapy.config import conf as _scapy_conf
        from scapy.sendrecv import sniff as _scapy_sniff
    except ImportError:
        if log_cb:
            log_cb("[!] scapy not available — DHCP sniffer disabled")
        t = threading.Thread(target=lambda: None, daemon=True)
        t.start()
        return t

    _stop = threading.Event()

    def _handler(pkt):
        try:
            if pkt.haslayer(DHCP):
                opts = pkt[DHCP].options
                hostname = ""
                for opt in opts:
                    if isinstance(opt, tuple) and opt[0] == "hostname":
                        hostname = opt[1].decode("utf-8", errors="ignore").strip()
                        break
                if not hostname:
                    return
                mac = ""
                if pkt.haslayer(BOOTP):
                    mac = ":".join(f"{b:02x}" for b in pkt[BOOTP].chaddr[:6])
                elif pkt.haslayer(Ether):
                    mac = pkt[Ether].src
                if not mac or not mac_tools.is_valid_mac(mac):
                    return
                mac = mac_tools.normalize_mac(mac)
                existing = load_dhcp_hostnames()
                if existing.get(mac) == hostname:
                    return
                if save_dhcp_hostnames(mac, hostname) and log_cb:
                    log_cb(f"[*] DHCP hostname captured: {mac} → {hostname}")
        except Exception:
            pass

    def _sniff_iface(iface):
        try:
            _scapy_sniff(
                iface=iface,
                filter="udp and (port 67 or port 68)",
                prn=_handler,
                store=0,
                stop_filter=lambda _: _stop.is_set(),
            )
        except PermissionError:
            pass
        except Exception as e:
            if log_cb:
                log_cb(f"[!] DHCP sniffer error on {iface}: {e}")

    def _run():
        ifaces = [i for i in interfaces if i]
        if not ifaces:
            return
        threads = []
        for iface in ifaces:
            t = threading.Thread(target=_sniff_iface, args=(iface,), daemon=True)
            t.start()
            threads.append(t)
        if log_cb:
            log_cb(f"[*] DHCP sniffer active on: {', '.join(ifaces)}")
        _stop.wait()
        for t in threads:
            t.join(timeout=3)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread._dhcp_stop = _stop  # type: ignore[attr-defined]
    return thread


def load_seen_state() -> dict:
    """Return {mac: ISO timestamp} of previously observed devices. Tolerant of missing file."""
    try:
        with open(seen_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {mac_tools.normalize_mac(k): v for k, v in data.items()
                    if isinstance(v, str) and v}
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {}


def save_seen_state(state: dict) -> bool:
    """Persist {mac: ISO timestamp} to data/last_seen.json (creates data/ as needed)."""
    clean = {mac_tools.normalize_mac(k): v for k, v in state.items()
             if mac_tools.is_valid_mac(k) and isinstance(v, str) and v}
    try:
        path = Path(seen_state_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(clean, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o644)
            except OSError:
                pass
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except OSError as e:
        print(f"[-] Failed to save last-seen state: {e}", file=sys.stderr)
        return False


def original_hostname_path() -> str:
    """Path to the persisted original hostname."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project, "data", "original_hostname.json")


def save_original_hostname(hostname: str) -> bool:
    """Persist the original hostname before rotation starts."""
    try:
        path = Path(original_hostname_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"hostname": hostname}, f)
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o644)
            except OSError:
                pass
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except OSError:
        return False


def load_original_hostname() -> str:
    """Return the saved original hostname, or "" if none saved."""
    try:
        with open(original_hostname_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return str(data.get("hostname", "") or "").strip()
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return ""


def load_registered(path: str = None) -> list:
    """Load registered devices from RegisteredAddresses.json.

    Returns [{"mac", "hostname"}] sorted by hostname; invalid entries skipped.
    Accepts object arrays (with "mac"/"hostname") or plain string arrays.
    """
    if path is None:
        path = registered_path()
    devices = []
    seen = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[-] Failed to load registered devices {path}: {e}", file=sys.stderr)
        return devices
    if not isinstance(data, list):
        return devices
    for entry in data:
        if isinstance(entry, dict):
            raw = entry.get("mac", "")
            hostname = str(entry.get("hostname", "") or "").strip()
            firewall_allow = bool(entry.get("firewall_allow", True))
        elif isinstance(entry, str):
            raw = entry
            hostname = ""
            firewall_allow = True
        else:
            continue
        mac = mac_tools.normalize_mac(raw)
        if mac_tools.is_valid_mac(mac) and mac not in seen:
            seen.add(mac)
            devices.append({
                "mac": mac,
                "hostname": hostname,
                "firewall_allow": firewall_allow,
            })
    devices.sort(key=lambda d: d["hostname"].lower())
    return devices


def hostname_map(path: str = None) -> dict:
    """Return {normalized_mac: hostname} from the registered-devices list.

    Tolerates a missing or malformed file (returns {}). Entries without a
    hostname are omitted. Used to seed row labels without touching the network.
    """
    if path is None:
        path = registered_path()
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return out
    if not isinstance(data, list):
        return out
    for entry in data:
        if isinstance(entry, dict):
            raw = entry.get("mac", "")
            hostname = str(entry.get("hostname", "") or "").strip()
        elif isinstance(entry, str):
            raw = entry
            hostname = ""
        else:
            continue
        mac = mac_tools.normalize_mac(raw)
        if mac_tools.is_valid_mac(mac) and hostname and mac not in out:
            out[mac] = hostname
    return out


def firewall_map(path: str = None) -> dict:
    """Return {normalized_mac: bool} firewall_allow flags from the register.

    Mirrors :func:`hostname_map`: tolerates a missing or malformed file
    (returns {}). Entries without a firewall_allow field default to True.
    """
    if path is None:
        path = registered_path()
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return out
    if not isinstance(data, list):
        return out
    for entry in data:
        if isinstance(entry, dict):
            raw = entry.get("mac", "")
            allowed = bool(entry.get("firewall_allow", True))
        elif isinstance(entry, str):
            raw = entry
            allowed = True
        else:
            continue
        mac = mac_tools.normalize_mac(raw)
        if mac_tools.is_valid_mac(mac) and mac not in out:
            out[mac] = allowed
    return out


def is_valid_hostname(name) -> bool:
    """Return True if ``name`` is a plausible RFC 1123/952 hostname.

    Rejects blank values and free-text label strings (spaces, unicode, double
    hyphens, leading/trailing hyphens). A single trailing dot (FQDN) is
    tolerated. 1-253 chars, dot-separated labels of 1-63 chars.
    """
    if not name:
        return False
    name = str(name).strip().rstrip(".")
    if not name or len(name) > 253:
        return False
    for label in name.split("."):
        if not (1 <= len(label) <= 63):
            return False
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label):
            return False
    return True


def blank_hostnames(devices, wordlist) -> tuple:
    """Return ``(devices, blanks)`` with non-valid hostnames blanked by words.

    ``devices`` is a list of ``{"mac", "hostname", ...}`` dicts; a shallow copy
    is returned. Each device whose hostname fails :func:`is_valid_hostname` is
    assigned a stable dictionary word derived from its MAC (hash -> word index,
    collision-skipping so every word is unique and never equals a kept valid
    hostname). ``blanks`` is a list of ``{"mac", "old", "new"}`` for reporting.
    Raises ``ValueError`` when the wordlist cannot cover all devices.
    """
    words = sorted({w.strip().lower() for w in wordlist if w and w.strip()})
    if not words:
        raise ValueError("wordlist is empty")
    kept = {str(d.get("hostname", "") or "").strip() for d in devices
            if is_valid_hostname(d.get("hostname", ""))}
    used = set(kept)
    out = [dict(d) for d in devices]
    blanks = []
    for d in out:
        old = str(d.get("hostname", "") or "").strip()
        if is_valid_hostname(old):
            continue
        mac = mac_tools.normalize_mac(d.get("mac", ""))
        seed = mac if mac_tools.is_valid_mac(mac) else old.lower()
        idx = int(hashlib.md5(seed.encode("utf-8", "ignore")).hexdigest(), 16) % len(words)
        word = words[idx]
        guard = 0
        while word in used and guard < len(words):
            idx = (idx + 1) % len(words)
            word = words[idx]
            guard += 1
        if word in used:
            raise ValueError("wordlist too small for the number of devices")
        used.add(word)
        blanks.append({"mac": mac, "old": old, "new": word})
        d["hostname"] = word
    return out, blanks


def _dig_reverse(ip: str, server: str = None, timeout: int = 2) -> str:
    """Run ``dig -x <ip>`` and return the first PTR name, or "".

    When *server* is given, uses ``@<server>``; otherwise falls back to the
    system resolver (resolv.conf).  Never raises.
    """
    if shutil.which("dig") is None:
        return ""
    cmd = ["dig"]
    if server:
        cmd.append(f"@{server}")
    cmd += ["-x", ip, "+short", f"+time={timeout}", "+tries=1"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 4)
    except (subprocess.SubprocessError, OSError):
        return ""
    for line in r.stdout.splitlines():
        name = line.strip().rstrip(".")
        if name and not name.startswith(";"):
            return name
    return ""


def _getent_host(ip: str) -> str:
    """Return the first hostname for *ip* from ``getent hosts``, or ""."""
    try:
        r = subprocess.run(["getent", "hosts", ip],
                           capture_output=True, text=True, timeout=3)
    except (subprocess.SubprocessError, OSError):
        return ""
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            return parts[1]
    return ""


def _ptr_via_router(ip: str) -> str:
    """Best-effort reverse-DNS via the on-link router, bypassing the VPN resolver.

    Derives the egress interface from ``ip route get <ip>``, uses that
    interface's gateway as the DNS target (falling back to the route's own
    ``via``), and queries it with ``dig -x``.  Falls back to system DNS
    (resolv.conf) and ``getent hosts`` for on-link IPs.  Never raises.
    """
    router = ""
    iface = ""
    try:
        r = subprocess.run(["ip", "route", "get", ip],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            parts = line.split()
            if "via" in parts and not router:
                router = parts[parts.index("via") + 1]
            if "dev" in parts and not iface:
                iface = parts[parts.index("dev") + 1]
            if router and iface:
                break
    except (subprocess.SubprocessError, OSError):
        return ""
    if not router and iface:
        router = get_gateway(iface)
    if router:
        name = _dig_reverse(ip, server=router)
        if name:
            return name
    name = _dig_reverse(ip)
    if name:
        return name
    return _getent_host(ip)


def resolve_hostnames_live(macs, known_map: dict = None, timeout: int = 3,
                           dhcp_hostnames: dict = None) -> tuple:
    """Resolve hostnames for MACs via live ARP cache + reverse-DNS + DHCP cache.

    Resolution chain: ARP cache → reverse-DNS → gethostbyaddr → DHCP cache → known_map.
    DHCP hostnames are sourced from passive DHCP packet sniffing (option 12).
    Returns ``(hostnames, last_seen)`` where *hostnames* is
    ``{normalized_mac: hostname}`` and *last_seen* is ``{normalized_mac: ISO_ts}``
    for MACs currently in the ARP cache.  Never raises.
    """
    import socket
    from datetime import datetime

    if known_map is None:
        known_map = hostname_map()
    if dhcp_hostnames is None:
        dhcp_hostnames = load_dhcp_hostnames()
    macs = [mac_tools.normalize_mac(m) for m in macs]
    macs = [m for m in macs if mac_tools.is_valid_mac(m)]
    cached = {}
    try:
        for entry in mac_tools.check_arp_cache():
            emac = mac_tools.normalize_mac(entry.get("mac", ""))
            if emac and emac not in cached:
                cached[emac] = entry
    except Exception:
        cached = {}
    out = {}
    last_seen = {}
    now = datetime.now().isoformat(timespec="seconds")
    for m in macs:
        entry = cached.get(m)
        ip = entry.get("ip", "") if entry else ""
        hostname = ""
        if ip:
            hostname = _ptr_via_router(ip)
            if not hostname:
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(timeout)
                try:
                    hostname, _aliases, _addrs = socket.gethostbyaddr(ip)
                except Exception:
                    hostname = ""
                finally:
                    socket.setdefaulttimeout(old_timeout)
        if not hostname:
            hostname = dhcp_hostnames.get(m, "")
        if not hostname:
            hostname = known_map.get(m, "")
        out[m] = hostname
        if entry:
            last_seen[m] = now
    return out, last_seen


def last_seen_for(mac: str) -> str:
    """Return the ISO last-seen timestamp for a MAC, or None if never seen."""
    mac = mac_tools.normalize_mac(mac)
    return load_seen_state().get(mac)


def merge_register(rows, register_path: str = None) -> int:
    """Merge MAC rows into RegisteredAddresses.json (update/insert, never remove).

    Existing entries keep their MAC and any extra fields; provided hostname /
    last_seen_at values overwrite empty/older ones. ``firewall_allow`` is
    handled bool-aware: when present in a row it is overwritten even when
    False (unlike the truthy-only hostname/last_seen_at handling); inserted
    entries default it to True. Unknown MACs are appended. The register is
    never shrunk. Missing register files are recreated from the given rows.
    Writes atomically (temp file + rename). Returns the number of updated +
    inserted entries, 0 on failure.
    """
    if register_path is None:
        register_path = registered_path()
    existing = []
    try:
        with open(register_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    existing.append(dict(entry))
                elif isinstance(entry, str):
                    existing.append({"mac": entry})
    except (OSError, ValueError, json.JSONDecodeError):
        existing = []

    by_mac = {}
    for entry in existing:
        mac = mac_tools.normalize_mac(entry.get("mac", ""))
        if mac_tools.is_valid_mac(mac) and mac not in by_mac:
            by_mac[mac] = entry

    changed = 0
    for row in rows:
        mac = mac_tools.normalize_mac(row.get("mac", ""))
        if not mac_tools.is_valid_mac(mac):
            continue
        hostname = str(row.get("hostname", "") or "").strip()
        last_seen = str(row.get("last_seen_at", "") or "").strip()
        if mac in by_mac:
            entry = by_mac[mac]
            if hostname:
                entry["hostname"] = hostname
            if last_seen:
                entry["last_seen_at"] = last_seen
            if "firewall_allow" in row:
                entry["firewall_allow"] = bool(row["firewall_allow"])
            changed += 1
        else:
            by_mac[mac] = {
                "mac": mac,
                "hostname": hostname,
                "last_seen_at": last_seen,
                "firewall_allow": bool(row.get("firewall_allow", True)),
            }
            changed += 1

    merged = sorted(by_mac.values(), key=lambda d: str(d.get("hostname", "") or "").lower())
    try:
        path = Path(register_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o644)
            except OSError:
                pass
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return changed
    except OSError as e:
        print(f"[-] Failed to merge register {register_path}: {e}", file=sys.stderr)
        return 0


def set_firewall_allow(mac, allowed, register_path: str = None) -> int:
    """Atomically set firewall_allow for one MAC in the register.

    Writes only the target field; all other fields and entry order are
    preserved. Returns 1 when the entry was updated, 0 when the MAC is
    invalid / not present / the write failed.
    """
    mac = mac_tools.normalize_mac(mac)
    if not mac_tools.is_valid_mac(mac):
        return 0
    if register_path is None:
        register_path = registered_path()
    try:
        with open(register_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return 0
    if not isinstance(data, list):
        return 0
    found = False
    for entry in data:
        if (isinstance(entry, dict)
                and mac_tools.normalize_mac(entry.get("mac", "")) == mac):
            entry["firewall_allow"] = bool(allowed)
            found = True
            break
    if not found:
        return 0
    try:
        path = Path(register_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o644)
            except OSError:
                pass
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return 1
    except OSError as e:
        print(f"[-] Failed to update firewall_allow in {register_path}: {e}",
              file=sys.stderr)
        return 0


def probe_mac_seen(mac: str, active: bool = False) -> tuple:
    """Check whether a MAC has been observed on the network.

    Passive: reads the kernel neighbor table (`mac_tools.check_arp_cache`). If
    `active` is True and the MAC is cached, also pings its IP to confirm it is
    currently reachable. Returns (seen, ip, state).
    """
    mac = mac_tools.normalize_mac(mac)
    if not mac_tools.is_valid_mac(mac):
        return False, "", ""
    entries = mac_tools.check_arp_cache(mac=mac)
    if not entries:
        return False, "", ""
    entry = entries[0]
    ip = entry.get("ip", "")
    state = entry.get("state", "")
    if active and ip:
        ok, _ = mac_tools.ping_device(ip, timeout=2)
        if not ok:
            return False, ip, f"{state} (no ping)"
    return True, ip, state


def _interface_net(iface: str):
    """Return (ip, prefix_len) for an interface's first non-loopback IPv4, else None."""
    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show", iface],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "inet " in line:
                cidr = line.split("inet ")[1].split()[0]
                ip, prefix = cidr.split("/")
                if not ip.startswith("127."):
                    return ip, int(prefix)
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    return None


def _pick_sweep_interface() -> str:
    """Pick a LAN interface for the active sweep (has IPv4 + non-self gateway)."""
    try:
        result = subprocess.run(
            ["ip", "-o", "link", "show"],
            capture_output=True, text=True, timeout=5
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    ifaces = []
    for line in result.stdout.splitlines():
        parts = line.split(": ")
        if len(parts) >= 2:
            name = parts[1].split("@")[0].strip()
            if name and name != "lo":
                ifaces.append(name)
    for iface in ifaces:
        ip = get_interface_ip(iface)
        gw = get_gateway(iface)
        if ip and gw and gw != ip:
            return iface
    return ""


def arp_sweep(iface: str, max_workers: int = 64, max_hosts: int = 4096,
              timeout: float = 1.0) -> int:
    """Actively probe the interface's subnet with arping (L2, bypasses the VPN).

    Requires root and the ``arping`` binary. Returns the number of hosts
    probed. Raises RuntimeError when the sweep cannot run (non-root, arping
    missing, or no IPv4 on the interface).
    """
    import ipaddress
    from concurrent.futures import ThreadPoolExecutor
    from itertools import islice

    if os.geteuid() != 0:
        raise RuntimeError("ARP sweep requires root")
    if shutil.which("arping") is None:
        raise RuntimeError("arping not installed")
    net = _interface_net(iface)
    if net is None:
        raise RuntimeError(f"no IPv4 address on {iface}")
    ip, prefix = net
    network = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
    hosts = islice(network.hosts(), max_hosts)
    probed = 0

    def probe(host):
        try:
            subprocess.run(
                ["arping", "-I", iface, "-c", "1", "-w", str(int(timeout)), host],
                capture_output=True, timeout=timeout + 1)
        except (subprocess.SubprocessError, OSError):
            pass

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for _ in ex.map(probe, hosts):
            probed += 1
    return probed


def discover_devices(iface: str = None, log_cb=None) -> list:
    """Discover devices on the local network via ARP sweep + DHCP cache.

    Returns a list of {"mac", "hostname", "source"} dicts where *source* is
    "arp" (seen in kernel neighbor table) or "dhcp" (captured via DHCP sniffer).
    ARP-sweeped devices take priority; DHCP-only entries fill gaps. Never raises.
    """
    from datetime import datetime

    if iface is None:
        iface = _pick_sweep_interface()

    # Step 1: ARP sweep to populate the kernel neighbor table
    if iface:
        try:
            probed = arp_sweep(iface)
            if log_cb:
                log_cb(f"[*] ARP sweep: probed {probed} hosts on {iface}")
        except RuntimeError as e:
            if log_cb:
                log_cb(f"[!] ARP sweep skipped: {e}")
    elif log_cb:
        log_cb("[!] ARP sweep skipped: no LAN interface found")

    # Step 2: Read the kernel neighbor table
    arp_devices = {}
    try:
        for entry in mac_tools.check_arp_cache():
            mac = mac_tools.normalize_mac(entry.get("mac", ""))
            if mac and mac_tools.is_valid_mac(mac) and mac not in arp_devices:
                arp_devices[mac] = entry
    except Exception:
        pass

    # Step 3: Merge DHCP cache
    dhcp_cache = load_dhcp_hostnames()

    # Step 4: Combine — ARP entries first, then DHCP-only entries
    seen = set()
    result = []
    now = datetime.now().isoformat(timespec="seconds")
    for mac, entry in arp_devices.items():
        hostname = dhcp_cache.get(mac, "")
        result.append({"mac": mac, "hostname": hostname, "source": "arp"})
        seen.add(mac)
    for mac, hostname in dhcp_cache.items():
        if mac not in seen:
            result.append({"mac": mac, "hostname": hostname, "source": "dhcp"})
            seen.add(mac)

    result.sort(key=lambda d: d.get("hostname", "").lower())
    if log_cb:
        log_cb(f"[*] Discovered {len(result)} device(s) "
               f"({len(arp_devices)} via ARP, {len(result) - len(arp_devices)} via DHCP)")
    return result


def scan_registered(path: str = None, active: bool = False, log_cb=None) -> tuple:
    """Probe every registered device and update the last-seen store.

    Stamps last_seen_at only on new sightings (never regresses an existing
    timestamp). Returns (seen_count, total, results) where results is a list of
    {"mac", "hostname", "seen", "ip", "state", "last_seen_at"}.
    """
    from datetime import datetime

    devices = load_registered(path)
    if not devices:
        if log_cb:
            log_cb("[!] No registered devices loaded")
        return 0, 0, []

    # Actively populate the neighbor table over L2 (bypasses any VPN tunnel)
    # when possible; falls back to the passive kernel table otherwise.
    sweep_iface = _pick_sweep_interface()
    if sweep_iface:
        try:
            probed = arp_sweep(sweep_iface)
            if log_cb:
                log_cb(f"[*] ARP sweep: probed {probed} hosts on {sweep_iface}")
        except RuntimeError as e:
            if log_cb:
                log_cb(f"[!] ARP sweep skipped: {e}")
    elif log_cb:
        log_cb("[!] ARP sweep skipped: no LAN interface found")

    # Read the kernel neighbor table once and index it by MAC.
    cached = {}
    for entry in mac_tools.check_arp_cache():
        emac = mac_tools.normalize_mac(entry.get("mac", ""))
        if emac and emac not in cached:
            cached[emac] = entry

    state = load_seen_state()
    now = datetime.now().isoformat(timespec="seconds")
    results = []
    seen_count = 0
    for i, dev in enumerate(devices, 1):
        entry = cached.get(dev["mac"])
        seen = entry is not None
        ip = entry.get("ip", "") if entry else ""
        state_s = entry.get("state", "") if entry else ""
        if seen and active and ip:
            ok, _ = mac_tools.ping_device(ip, timeout=2)
            if not ok:
                seen = False
                state_s = f"{state_s} (no ping)"
        last_seen = ""
        if seen:
            seen_count += 1
            if dev["mac"] not in state:
                state[dev["mac"]] = now
            last_seen = state[dev["mac"]]
            if log_cb:
                log_cb(f"[{i}/{len(devices)}] SEEN  {dev['mac']}  {dev['hostname']}"
                       f"  ({ip}, {state_s})")
        else:
            last_seen = state.get(dev["mac"], "")
            if log_cb and i % 25 == 0:
                log_cb(f"[{i}/{len(devices)}] checked… ({seen_count} seen so far)")
        results.append({
            "mac": dev["mac"],
            "hostname": dev["hostname"],
            "seen": seen,
            "ip": ip,
            "state": state_s,
            "last_seen_at": last_seen,
        })

    save_seen_state(state)
    if log_cb:
        log_cb(f"[*] Scan done: {seen_count}/{len(devices)} registered devices currently seen")
    return seen_count, len(devices), results


# ---------------------------------------------------------------------------
# Rotation worker
# ---------------------------------------------------------------------------

class RotationWorker(threading.Thread):
    def __init__(self, iface, macs, interval, log_cb, done_cb, down_delay=0,
                 register_path=None, hostname_enabled=False,
                 hostname_pattern="device-{mac_suffix}"):
        super().__init__(daemon=True)
        self.iface = iface
        self.macs = macs          # list of (enabled: bool, mac: str)
        self.interval = max(interval, 1)
        self.down_delay = max(int(down_delay), 0)
        self.log_cb = log_cb
        self.done_cb = done_cb
        self.register_path = register_path or registered_path()
        self.hostname_enabled = hostname_enabled
        self.hostname_pattern = hostname_pattern
        self._stop = threading.Event()
        self._hold = threading.Event()
        self.backed_up = False
        self.original_mac = ""
        self.original_hostname = ""

    def stop(self):
        self._stop.set()
        self._hold.set()

    def run(self):
        try:
            self._run()
        except Exception as e:
            self.log_cb(f"[!] Rotation worker error: {e}")
        finally:
            self.done_cb()

    def _run(self):
        enabled = [(m) for (en, m) in self.macs if en and mac_tools.is_valid_mac(m)]
        if not enabled:
            self.log_cb("[!] No enabled valid MACs configured")
            return

        ok, current = mac_tools.get_current_mac(self.iface)
        if ok:
            self.original_mac = current

        if self.hostname_enabled:
            self.original_hostname = get_hostname()
            save_original_hostname(self.original_hostname)
            self.log_cb(f"[*] Original hostname: {self.original_hostname}")

        idx = 0
        enabled_count = len(enabled)
        disabled_count = len(self.macs) - enabled_count
        summary = f"{enabled_count} MACs enabled"
        if disabled_count:
            summary += f", {disabled_count} disabled"
        self.log_cb(f"[*] Rotation started on {self.iface} ({summary}, "
                    f"interval {self.interval}s)")
        for i, mac in enumerate(enabled, 1):
            self.log_cb(f"    [{i}] {mac}")
        while not self._stop.is_set():
            target = enabled[idx % len(enabled)]

            if not self.backed_up:
                if self.original_mac:
                    row = mac_tools.backup_mac(self.iface, self.original_mac)
                    self.backed_up = row is not None
                    if self.backed_up:
                        self.log_cb(f"[*] Original MAC backed up: {self.original_mac}")
                    else:
                        self.log_cb("[!] Could not record original MAC backup")

            ok_change, msg = change_mac_delayed(
                self.iface, target, self.down_delay, sleep_cb=self._hold.wait)
            self.log_cb(f"[{('ok' if ok_change else '!!')}] change_mac({target}): {msg}")

            if ok_change:
                if self.hostname_enabled:
                    new_hostname = generate_hostname(self.hostname_pattern, target)
                    h_ok, h_msg = set_hostname(new_hostname)
                    self.log_cb(f"[{'ok' if h_ok else '!!'}] hostname: {h_msg}")
                    if h_ok:
                        mdns_ok, mdns_msg = restart_mdns()
                        self.log_cb(f"[{'ok' if mdns_ok else '!!'}] {mdns_msg}")

                renew_ok, renew_msg = dhcp_renew(self.iface)
                self.log_cb(f"[{'ok' if renew_ok else '!!'}] {renew_msg}")
                conn_ok, conn_msg = test_connection(self.iface)
                self.log_cb(f"[{'ok' if conn_ok else '!!'}] connectivity: {conn_msg}")
                fw = detect_firewall_allow(self.iface, probe=(conn_ok, conn_msg))
                if fw is not None:
                    if set_firewall_allow(target, fw, self.register_path):
                        self.log_cb(
                            f"[*] firewall allow={str(fw).lower()} recorded for {target}")
                    else:
                        self.log_cb(
                            f"[!] {target} not in register — firewall flag not recorded")
                if conn_ok:
                    self.log_cb(f"[*] Holding {target} for {self.interval}s")
                    self._hold.wait(self.interval)
                    self._hold.clear()
                else:
                    self.log_cb(f"[>] {target} failed connectivity — advancing")
            else:
                self.log_cb(f"[>] Could not apply {target} — advancing")

            if self._stop.is_set():
                break
            idx += 1

        self.log_cb("[*] Rotation stopped")
