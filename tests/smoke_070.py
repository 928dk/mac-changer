#!/usr/bin/env python3
"""Smoke tests for spec 070: list enrichment GUI (no root required, display-gated).

Checks:
  1. Row labels (hostname + last-seen) and _collect_row_data enriched output.
  2. Select all / select none tick and untick every row.
  3. Sort by MAC and hostname preserves the enabled state.
  4. Filter hides non-matching rows (display-only); clearing restores all.
  5. (spec 099) Header buttons sort, toggle direction, show ▲/▼ indicator.
  6. (spec 099) Removing a row leaves no grid gaps; header/row column widths match.
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

import rotation_engine as re
from src import mac_changer as mc


def _fresh_app(tmp):
    real = (re.config_path, re.registered_path, re.seen_state_path)
    re.config_path = lambda: os.path.join(tmp, "config.json")
    re.registered_path = lambda: os.path.join(tmp, "RegisteredAddresses.json")
    re.seen_state_path = lambda: os.path.join(tmp, "seen.json")
    real_maps = (mc.hostname_map, mc.firewall_map)
    mc.hostname_map = lambda path=None: {}
    mc.firewall_map = lambda path=None: {}

    def restore():
        re.config_path, re.registered_path, re.seen_state_path = real
        mc.hostname_map, mc.firewall_map = real_maps

    app = mc.MacChangerApp()
    return app, restore


def test_row_labels_and_data(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        app, restore = _fresh_app(d)
        try:
            app._add_mac_row(mac="AA:BB:CC:DD:EE:FF", hostname="Host-A")
            r = app.mac_rows[-1]
            assert r["hostname_lbl"].cget("text") == "Host-A"
            assert r["last_lbl"].cget("text") == "never"
            data = app._collect_row_data()[-1]
            assert data["mac"] == "AA:BB:CC:DD:EE:FF"
            assert data["hostname"] == "Host-A"
            assert data["last_seen_at"] == ""
            app.destroy()
        finally:
            restore()
    print("  OK: row shows hostname + last-seen labels; _collect_row_data enriched")


def test_select_all_none(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        app, restore = _fresh_app(d)
        try:
            app._add_mac_row(mac="AA:BB:CC:DD:EE:FF")
            app._add_mac_row(mac="00:11:22:33:44:55")
            app._select_all()
            assert all(bool(r["check"].get()) for r in app.mac_rows)
            app._select_none()
            assert all(not bool(r["check"].get()) for r in app.mac_rows)
            app.destroy()
        finally:
            restore()
    print("  OK: select all / select none tick and untick every row")


def test_sort_mac_and_hostname_preserve_enabled(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        app, restore = _fresh_app(d)
        try:
            app._add_mac_row(mac="AA:BB:CC:DD:EE:FF", enabled=False, hostname="Zulu")
            app._add_mac_row(mac="00:11:22:33:44:55", enabled=True, hostname="Alpha")
            app._sort_rows("mac")
            assert app.mac_rows[0]["entry"].get() == "00:11:22:33:44:55"
            assert bool(app.mac_rows[0]["check"].get()) is True
            assert app.mac_rows[1]["entry"].get() == "AA:BB:CC:DD:EE:FF"
            assert bool(app.mac_rows[1]["check"].get()) is False
            app._sort_rows("hostname")
            assert app.mac_rows[0]["entry"].get() == "00:11:22:33:44:55"  # Alpha first
            assert bool(app.mac_rows[0]["check"].get()) is True
            assert app.mac_rows[1]["entry"].get() == "AA:BB:CC:DD:EE:FF"
            assert bool(app.mac_rows[1]["check"].get()) is False
            app.destroy()
        finally:
            restore()
    print("  OK: sort by MAC + hostname preserves enabled state")


def test_filter_display_only(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        app, restore = _fresh_app(d)
        try:
            app._add_mac_row(mac="AA:BB:CC:DD:EE:FF", hostname="Server-One")
            app._add_mac_row(mac="00:11:22:33:44:55", hostname="Laptop-Two")
            app.filter_var.set("laptop")
            app._apply_filter()
            visible = [r for r in app.mac_rows if r["entry"].winfo_manager() == "grid"]
            assert len(visible) == 1, f"expected 1 visible, got {len(visible)}"
            assert visible[0]["entry"].get() == "00:11:22:33:44:55"
            app.filter_var.set("")
            app._apply_filter()
            assert all(r["entry"].winfo_manager() == "grid" for r in app.mac_rows)
            app.destroy()
        finally:
            restore()
    print("  OK: filter hides non-matching rows (display-only); clearing restores all")


def test_header_sort_and_toggle(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        app, restore = _fresh_app(d)
        try:
            app._add_mac_row(mac="AA:BB:CC:DD:EE:FF", enabled=False, hostname="Zulu")
            app._add_mac_row(mac="00:11:22:33:44:55", enabled=True, hostname="Alpha")
            assert set(app._header_buttons) >= {"mac", "hostname", "last_seen", "fw"}
            h = app._header_buttons
            h["hostname"].invoke()
            assert app.mac_rows[0]["entry"].get() == "00:11:22:33:44:55"  # Alpha asc
            assert bool(app.mac_rows[0]["check"].get()) is True
            assert "▲" in h["hostname"].cget("text")
            h["hostname"].invoke()
            assert app.mac_rows[0]["entry"].get() == "AA:BB:CC:DD:EE:FF"  # Zulu desc
            assert "▼" in h["hostname"].cget("text")
            h["mac"].invoke()
            assert app.mac_rows[0]["entry"].get() == "00:11:22:33:44:55"  # MAC asc reset
            assert "▲" in h["mac"].cget("text")
            assert "▲" not in h["hostname"].cget("text")
            app.destroy()
        finally:
            restore()
    print("  OK: header click sorts + toggles with ▲/▼ indicator")


def test_remove_row_reindexes_and_alignment(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        app, restore = _fresh_app(d)
        try:
            app._add_mac_row(mac="AA:BB:CC:DD:EE:FF")
            app._add_mac_row(mac="00:11:22:33:44:55")
            app._add_mac_row(mac="11:22:33:44:55:66")
            for i in range(len(mc.COLUMNS)):
                hw = app.mac_header.grid_columnconfigure(i, "minsize")
                rw = app.mac_frame.grid_columnconfigure(i, "minsize")
                assert hw == rw, f"column {i} width mismatch: {hw} != {rw}"
            app._remove_mac_row(app.mac_rows[1]["remove_btn"])
            assert len(app.mac_rows) == 2
            for i, r in enumerate(app.mac_rows):
                assert r["entry"].grid_info()["row"] == i, f"gap after remove at {i}"
            app.destroy()
        finally:
            restore()
    print("  OK: removal re-indexes grid rows; header/row column widths match")


def main():
    display_ok = os.environ.get("DISPLAY", "") != ""
    for t in (test_row_labels_and_data, test_select_all_none,
              test_sort_mac_and_hostname_preserve_enabled, test_filter_display_only,
              test_header_sort_and_toggle, test_remove_row_reindexes_and_alignment):
        t(display_ok)
    print("ALL SPEC-070 SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
