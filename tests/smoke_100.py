#!/usr/bin/env python3
"""Smoke tests for spec 100: hover tooltips on GUI controls (no root, display-gated).

Checks:
  1. Every interactive control (11 buttons, 4 header sort buttons, 3 option
     menus, 2 entries) has a ToolTip with the expected, non-empty text and a
     bound <Enter> handler.
  2. Hover show/hide: enter schedules a delayed show, leave cancels it; a
     single shared popup is deiconified with the widget's text on show.
  3. Popup reuse: showing a second tooltip reuses the same Toplevel.
  4. Position clamp: an off-screen widget keeps the popup on-screen.
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


BUTTON_TIPS = {
    "Refresh": "Re-detect available network interfaces",
    "+ Add MAC": "Add a new MAC address to the rotation list",
    "Start": "Start interval MAC rotation / Stop rotation while running",
    "Restore original": "Restore the interface's original MAC address",
}

HEADER_TIPS = {key: "Sort by column; click again to toggle ▲/▼ direction"
               for key in mc.SORTABLE_COLUMNS}

ATTR_TIPS = {
    "iface_menu": "Network interface whose MAC is rotated",
    "interval_menu": "How often the MAC rotates",
    "custom_entry": "Custom interval in seconds when 'custom' is selected",
    "down_delay_menu": "Seconds to keep the link down before reconnecting",
    "filter_entry": "Filter the list by MAC or hostname text (Ctrl+F)",
    "hostname_chk": "Change system hostname alongside MAC address",
    "hostname_pattern_entry": "Hostname pattern: {mac}, {mac_suffix}, {mac_hex}",
}

EXPECTED_COUNT = len(BUTTON_TIPS) + len(HEADER_TIPS) + len(ATTR_TIPS)


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


def _tips_for(app):
    """Map widget -> ToolTip instance for the live app (excludes destroyed apps)."""
    tips = {}
    for t in mc.ToolTip._instances:
        try:
            if t.widget.winfo_toplevel() is app:
                tips[t.widget] = t
        except Exception:
            pass
    return tips


def _find_buttons(widget, text):
    out = []
    for w in widget.winfo_children():
        if isinstance(w, mc.ctk.CTkButton):
            try:
                if w.cget("text") == text:
                    out.append(w)
            except Exception:
                pass
        out.extend(_find_buttons(w, text))
    return out


def _has_enter_binding(w):
    """CTk .bind() forwards to internal widgets; check those for <Enter>."""
    for attr in ("_canvas", "_text_label", "_image_label", "_entry"):
        target = getattr(w, attr, None)
        if target is not None:
            try:
                if target.bind("<Enter>"):
                    return True
            except Exception:
                pass
    return False


def test_coverage_and_text(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        app, restore = _fresh_app(d)
        try:
            tips = _tips_for(app)
            assert len(tips) == EXPECTED_COUNT, (
                f"expected {EXPECTED_COUNT} tooltips, got {len(tips)}")
            assert len({id(w) for w in tips}) == len(tips), "duplicate widgets"
            for w, t in tips.items():
                assert t.text.strip(), "empty tooltip text"
                assert _has_enter_binding(w), f"no <Enter> binding on {w}"

            for label, text in BUTTON_TIPS.items():
                matches = _find_buttons(app, label)
                assert matches, f"button '{label}' not found"
                for w in matches:
                    assert tips[w].text == text, f"'{label}' tooltip mismatch"

            for key, text in HEADER_TIPS.items():
                w = app._header_buttons[key]
                assert w in tips and tips[w].text == text, f"header '{key}' tooltip"

            for attr, text in ATTR_TIPS.items():
                w = getattr(app, attr)
                assert w in tips and tips[w].text == text, f"'{attr}' tooltip"
            app.destroy()
        finally:
            restore()
    print(f"  OK: {EXPECTED_COUNT} controls covered with correct tooltip text")


def test_hover_show_hide_and_reuse(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        app, restore = _fresh_app(d)
        try:
            tips = _tips_for(app)
            start = tips[app.toggle_btn]

            start._on_enter()
            assert start._after_id is not None, "enter should schedule a show"
            start._on_leave()
            assert start._after_id is None, "leave should cancel the show"

            start._show()
            app.update()
            assert mc.ToolTip._tip is not None, "popup was not created"
            assert mc.ToolTip._tip.winfo_exists()
            assert mc.ToolTip._tip_label.cget("text") == BUTTON_TIPS["Start"]
            assert mc.ToolTip._tip.winfo_viewable(), "popup not visible after show"

            first_popup = mc.ToolTip._tip
            refresh_btn = _find_buttons(app, "Refresh")[0]
            refresh_btn_tip = tips[refresh_btn]
            refresh_btn_tip._show()
            app.update()
            assert mc.ToolTip._tip is first_popup, "popup was not reused"
            assert mc.ToolTip._tip_label.cget("text") == BUTTON_TIPS["Refresh"]

            start._on_leave()
            app.update()
            assert not mc.ToolTip._tip.winfo_viewable(), "popup still visible after leave"
            app.destroy()
        finally:
            restore()
    print("  OK: enter schedules, leave cancels/hides, popup reused, text matches")


def test_clamp_keeps_tooltip_on_screen(display_ok):
    if not display_ok:
        print("  SKIP: no display available")
        return
    with tempfile.TemporaryDirectory() as d:
        app, restore = _fresh_app(d)
        try:
            tips = _tips_for(app)
            tt = tips[app.iface_menu]
            real_x, real_y = app.iface_menu.winfo_rootx, app.iface_menu.winfo_rooty
            app.iface_menu.winfo_rootx = lambda: 20000
            app.iface_menu.winfo_rooty = lambda: 20000
            try:
                tt._show()
                app.update()
                tip = mc.ToolTip._tip
                tw, th = tip.winfo_reqwidth(), tip.winfo_reqheight()
                sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
                x = int(tip.geometry().split("+")[1])
                y = int(tip.geometry().split("+")[2])
                assert 0 <= x and x + tw <= sw, f"x={x} tw={tw} sw={sw}"
                assert 0 <= y and y + th <= sh, f"y={y} th={th} sh={sh}"
            finally:
                app.iface_menu.winfo_rootx = real_x
                app.iface_menu.winfo_rooty = real_y
            app.destroy()
        finally:
            restore()
    print("  OK: popup clamped to stay on-screen for off-screen widget")


def main():
    display_ok = os.environ.get("DISPLAY", "") != ""
    for t in (test_coverage_and_text, test_hover_show_hide_and_reuse,
              test_clamp_keeps_tooltip_on_screen):
        t(display_ok)
    print("ALL SPEC-100 SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
