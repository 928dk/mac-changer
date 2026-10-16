#!/usr/bin/env python3
"""Smoke tests for spec 069: down-delay + scroll fix (no root required).

Checks:
  1. change_mac_delayed with down_delay=0 mirrors mac_tools.change_mac sequence
     (verified via a fake subprocess runner monkeypatch).
  2. change_mac_delayed sleeps between down and up when delay > 0.
  3. Config round-trip: down_delay_seconds survives save/load, coerced int.
  4. RotationWorker accepts down_delay and calls change_mac_delayed.
  5. SafeScrollableFrame._check_if_valid_scroll tolerates str / None widgets.
  6. GUI builds with the down-delay selector (requires display).
"""
import os
import sys
import tempfile
from pathlib import Path

DIR = Path(__file__).resolve().parents[1]
FISHEYE_GUI = DIR.parent / "fisheye-gui"
for p in (str(FISHEYE_GUI), str(DIR), str(DIR / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import rotation_engine as re
from src import mac_changer as mc


# --- 1 + 2: change_mac_delayed sequence + sleep -----------------------------
def test_delayed_sequence_and_sleep():
    calls = []
    delays = []

    def fake_run(cmd, **kw):
        calls.append(cmd)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    orig_run = re.subprocess.run
    orig_get = re.mac_tools.get_current_mac
    re.subprocess.run = fake_run
    re.mac_tools.get_current_mac = lambda iface: (True, "aa:bb:cc:dd:ee:ff")
    try:
        ok, msg = re.change_mac_delayed("eth0", "AA:BB:CC:DD:EE:FF", 0)
        assert ok, msg
        assert delays == [], delays
        assert len(calls) == 3, calls  # down, address, up
        assert calls[0][0:4] == ["ip", "link", "set", "eth0"]
        assert calls[0][-1] == "down"
        assert calls[1][-1] == "AA:BB:CC:DD:EE:FF"
        assert calls[2][-1] == "up"

        calls.clear()
        re.change_mac_delayed("eth0", "AA:BB:CC:DD:EE:FF", 3, sleep_cb=delays.append)
        assert delays == [3], delays
        assert len(calls) == 3, calls
    finally:
        re.subprocess.run = orig_run
        re.mac_tools.get_current_mac = orig_get
    print("  OK: change_mac_delayed sequence + delay-0/no-sleep + delay-3/sleep")


def test_delayed_down_failure():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)

        class R:
            returncode = 1 if cmd[-1] == "down" else 0
            stdout = ""
            stderr = "boom"

        return R()

    orig_run = re.subprocess.run
    re.subprocess.run = fake_run
    try:
        ok, msg = re.change_mac_delayed("eth0", "AA:BB:CC:DD:EE:FF", 5)
        assert not ok
        assert "down" in msg and "boom" in msg, msg
        assert len(calls) == 1, calls  # no sleep, no further cmds on down-failure
    finally:
        re.subprocess.run = orig_run
    print("  OK: down failure short-circuits (no sleep, error surfaced)")


# --- 3: config round-trip ---------------------------------------------------
def test_config_round_trip():
    with tempfile.TemporaryDirectory() as d:
        cfg = re.default_config()
        assert cfg["down_delay_seconds"] == 0
        cfg["down_delay_seconds"] = 10
        orig = re.config_path
        re.config_path = lambda: os.path.join(d, "config.json")
        try:
            assert re.save_config(cfg)
            loaded = re.load_config()
            assert loaded["down_delay_seconds"] == 10, loaded
            cfg["down_delay_seconds"] = "junk"
            re.save_config(cfg)
            assert re.load_config()["down_delay_seconds"] == 0
        finally:
            re.config_path = orig
    print("  OK: config round-trip + int coercion")


# --- 4: RotationWorker down_delay wiring ------------------------------------
def test_worker_down_delay_param():
    w = re.RotationWorker("eth0", [(True, "AA:BB:CC:DD:EE:FF")], 60,
                          log_cb=lambda s: None, done_cb=lambda: None,
                          down_delay="7")
    assert w.down_delay == 7, w.down_delay
    w2 = re.RotationWorker("eth0", [], 60, log_cb=print, done_cb=lambda: None)
    assert w2.down_delay == 0
    print("  OK: RotationWorker down_delay param (str coercion + default)")


# --- 5: SafeScrollableFrame string-widget guard -----------------------------
def test_safe_scrollable_guard():
    try:
        import customtkinter as ctk
    except ImportError:
        print("  SKIP: customtkinter unavailable")
        return
    root = ctk.CTk()
    root.withdraw()
    f = mc.SafeScrollableFrame(root, height=100)
    assert f._check_if_valid_scroll(".!some.stale.path") is False
    assert f._check_if_valid_scroll(None) is False
    assert f._check_if_valid_scroll(f._parent_canvas) is True
    f.destroy()
    root.destroy()
    print("  OK: SafeScrollableFrame tolerates str/None widgets")


# --- 6: GUI builds with the selector ----------------------------------------
def test_gui_selector(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        orig = re.config_path
        re.config_path = lambda: os.path.join(d, "config.json")
        try:
            app = mc.MacChangerApp()
            assert hasattr(app, "down_delay_menu")
            assert app._selected_down_delay() == 0
            app.down_delay_var.set("10 s")
            assert app._selected_down_delay() == 10
            assert app._delay_label_for(10) == "10 s"
            app.destroy()
        finally:
            re.config_path = orig
    print("  OK: GUI builds with down-delay selector + selection math")


def main():
    display_ok = os.environ.get("DISPLAY", "") != ""
    for t in (test_delayed_sequence_and_sleep, test_delayed_down_failure,
              test_config_round_trip, test_worker_down_delay_param,
              test_safe_scrollable_guard):
        t()
    test_gui_selector(display_ok)
    print("ALL SPEC-069 SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
