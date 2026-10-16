#!/usr/bin/env python3
"""mac-changer — interval MAC rotation app (GUI).

CustomTkinter front-end over the GUI-independent rotation engine in
`src/rotation_engine.py`. Launch via `gui.sh` (root-elevated).
"""
import os
import sys
import tkinter as tk
from tkinter import TclError

from rotation_engine import (
    __version__,
    INTERVALS,
    DEFAULT_INTERVAL,
    RotationWorker,
    config_path,
    load_config,
    save_config,
    load_mac_list,
    export_mac_list,
    scan_registered,
    discover_devices,
    hostname_map,
    firewall_map,
    resolve_hostnames_live,
    load_seen_state,
    save_seen_state,
    load_original_hostname,
    merge_register,
    get_loaded_macs,
    loaded_macs_summary,
    get_hostname,
    setup_file_logger,
    start_dhcp_sniffer,
    dhcp_hostnames_path,
    mac_tools,
)

try:
    import customtkinter as ctk
except ImportError:
    print("customtkinter not installed. Run: pip install customtkinter", file=sys.stderr)
    sys.exit(1)


DOWN_DELAY_OPTIONS = [("Off", 0), ("1 s", 1), ("2 s", 2), ("3 s", 3),
                      ("5 s", 5), ("10 s", 10), ("15 s", 15), ("30 s", 30)]

AUTO_RESOLVE_OPTIONS = [("60 s", 60_000), ("120 s", 120_000),
                        ("5 min", 300_000), ("Off", 0)]

# Shared table layout: (row-key, header label, column min width). The same
# tuple drives grid_columnconfigure on both the frozen header bar and the
# scrollable row area so every cell in a column aligns to the same x offset.
COLUMNS = [
    ("rotate", "✓", 36),
    ("mac", "MAC", 200),
    ("hostname", "Hostname", 180),
    ("last_seen", "Last seen", 150),
    ("fw", "FW", 36),
    ("remove", "", 36),
]
COLUMN_LABELS = {key: label for key, label, _width in COLUMNS}
SORTABLE_COLUMNS = ("mac", "hostname", "last_seen", "fw")


class SafeScrollableFrame(ctk.CTkScrollableFrame):
    """CTkScrollableFrame that tolerates string-valued ``event.widget``.

    customtkinter 6.0.0's ``_check_if_valid_scroll`` assumes ``event.widget`` is
    a widget object, but Tk delivers a Tcl pathname string when the widget under
    the cursor is destroyed mid-scroll (e.g. a MAC row removed while scrolling),
    causing ``AttributeError: 'str' object has no attribute 'master'``. Override
    resolves the pathname and treats unresolvable/stale widgets as not scrollable.
    """

    def _check_if_valid_scroll(self, widget):
        if widget is None:
            return False
        if isinstance(widget, str):
            try:
                widget = self.nametowidget(widget)
            except (KeyError, TclError):
                return False
        return super()._check_if_valid_scroll(widget)


class ToolTip:
    """Hover help popup attached to a widget.

    CustomTkinter has no native tooltip support, so this helper binds
    ``<Enter>`` / ``<Leave>`` / ``<ButtonPress>`` on the target widget and
    shows a delayed, passive ``tk.Toplevel(overrideredirect=True)`` label near
    the widget. One popup is shared across all tooltips; leaving the widget or
    pressing any mouse button cancels a pending show and hides the popup.
    """

    SHOW_DELAY_MS = 400
    _tip = None
    _tip_label = None
    _instances = []

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._after_id = None
        self._instances.append(self)
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    # -- event handlers --------------------------------------------------

    def _on_enter(self, _event=None):
        if self._after_id is not None:
            self._cancel()
        self._after_id = self.widget.after(self.SHOW_DELAY_MS, self._show)

    def _on_leave(self, _event=None):
        self._cancel()

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except TclError:
                pass
            self._after_id = None
        self._hide()

    # -- popup -----------------------------------------------------------

    def _tip_alive(self):
        if ToolTip._tip is None:
            return False
        try:
            return bool(ToolTip._tip.winfo_exists())
        except TclError:
            return False

    def _ensure_tip(self):
        if not self._tip_alive():
            tip = tk.Toplevel(self.widget)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            label = ctk.CTkLabel(
                tip, text=self.text, justify="left", corner_radius=6,
                fg_color=("gray75", "gray25"),
                text_color=("gray10", "white"), padx=8, pady=4)
            label.pack()
            ToolTip._tip = tip
            ToolTip._tip_label = label
        return ToolTip._tip

    def _show(self):
        self._after_id = None
        tip = self._ensure_tip()
        ToolTip._tip_label.configure(text=self.text)
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty()
        w = self.widget.winfo_width()
        h = self.widget.winfo_height()
        tip.update_idletasks()
        tw = tip.winfo_reqwidth()
        th = tip.winfo_reqheight()
        pad = 8
        x = min(x + w + pad, self.widget.winfo_screenwidth() - tw - 4)
        y = min(y + h + pad, self.widget.winfo_screenheight() - th - 4)
        tip.geometry(f"+{max(4, x)}+{max(4, y)}")
        tip.deiconify()
        tip.lift()

    def _hide(self):
        if self._tip_alive():
            try:
                ToolTip._tip.withdraw()
            except TclError:
                pass


class MacChangerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("mac-changer — interval MAC rotation")
        self.cfg = load_config()
        self.geometry(self.cfg.get("window_geometry", "760x640"))
        self.minsize(640, 550)

        self.worker = None
        self.mac_rows = []
        self._sort_col = None
        self._sort_reverse = False
        self._header_buttons = {}
        self._hostnames = hostname_map()
        self._fw = firewall_map()
        self._seen = load_seen_state()
        self.filter_var = ctk.StringVar()
        self.interval_var = ctk.StringVar(value=self.cfg["interval_label"]
                                          if self.cfg["interval_label"] in [i[0] for i in INTERVALS]
                                          else "30 min")
        self._col_widths = dict(self.cfg.get("column_widths",
                                              {"rotate": 36, "mac": 200, "hostname": 180,
                                               "last_seen": 150, "fw": 36, "remove": 36}))
        self._file_logger = setup_file_logger()

        self._empty_state_label = None
        self._dhcp_sniffer_var = ctk.BooleanVar(
            value=self.cfg.get("dhcp_hostnames_enabled", True))
        self._auto_resolve_var = ctk.StringVar(
            value=self._auto_resolve_label_for(
                self.cfg.get("auto_resolve_interval_ms", 60_000)))

        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self._populate_config()
        self._refresh_interfaces()

        if self._dhcp_sniffer_var.get():
            ifaces = self._active_interfaces()
            if ifaces:
                self._dhcp_sniffer = start_dhcp_sniffer(
                    ifaces, log_cb=self._log_threadsafe)
            else:
                self._dhcp_sniffer = None
        else:
            self._dhcp_sniffer = None

        self._auto_resolve_id = None
        self._start_auto_resolve()

    @staticmethod
    def _tt(widget, text):
        """Attach a hover tooltip to *widget* and return it for chaining."""
        ToolTip(widget, text)
        return widget

    # ---- Menu bar -----------------------------------------------------------

    def _build_menu(self):
        self._menubar = tk.Menu(self)

        file_menu = tk.Menu(self._menubar, tearoff=0)
        file_menu.add_command(label="New list", command=self._new_list)
        file_menu.add_separator()
        file_menu.add_command(label="Import list…", accelerator="Ctrl+I",
                              command=self._import_list)
        file_menu.add_command(label="Export list…", accelerator="Ctrl+E",
                              command=self._export_list)
        file_menu.add_separator()
        file_menu.add_command(label="Save list", accelerator="Ctrl+S",
                              command=self._save_list)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Ctrl+Q",
                              command=self.on_close)
        self._menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(self._menubar, tearoff=0)
        edit_menu.add_command(label="Add MAC", accelerator="Ctrl+A",
                              command=self._add_mac_row)
        edit_menu.add_command(label="Move up", accelerator="Ctrl+Up",
                              command=lambda: self._move_selected(-1))
        edit_menu.add_command(label="Move down", accelerator="Ctrl+Down",
                              command=lambda: self._move_selected(1))
        edit_menu.add_separator()
        edit_menu.add_command(label="Select all", accelerator="Ctrl+Shift+A",
                              command=self._select_all)
        edit_menu.add_command(label="Select none", accelerator="Ctrl+Shift+N",
                              command=self._select_none)
        edit_menu.add_command(label="Delete selected", accelerator="Delete",
                              command=self._delete_selected)
        edit_menu.add_separator()
        edit_menu.add_command(label="Clear list", command=self._clear_list)
        self._menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(self._menubar, tearoff=0)
        sort_menu = tk.Menu(view_menu, tearoff=0)
        for key in SORTABLE_COLUMNS:
            sort_menu.add_command(label=COLUMN_LABELS[key],
                                  command=lambda k=key: self._sort_rows(k))
        view_menu.add_cascade(label="Sort by", menu=sort_menu)
        view_menu.add_separator()
        view_menu.add_command(label="Discover devices",
                              command=self._discover_devices)
        view_menu.add_command(label="Resolve hostnames",
                              command=self._resolve_hostnames)
        view_menu.add_command(label="Scan registered",
                              command=self._scan_registered)
        view_menu.add_separator()
        view_menu.add_command(label="Filter", accelerator="Ctrl+F",
                              command=self._focus_filter)
        self._menubar.add_cascade(label="View", menu=view_menu)

        settings_menu = tk.Menu(self._menubar, tearoff=0)
        self._iface_menu_var = tk.StringVar(value="Refresh needed")
        self._iface_menu = tk.Menu(settings_menu, tearoff=0)
        self._iface_menu_var.set("Refresh needed")
        settings_menu.add_cascade(label="Interface", menu=self._iface_menu)
        settings_menu.add_separator()
        self._dhcp_toggle_menu_var = self._dhcp_sniffer_var
        settings_menu.add_checkbutton(
            label="Passive DHCP capture",
            variable=self._dhcp_toggle_menu_var,
            command=self._on_dhcp_toggle)
        auto_resolve_menu = tk.Menu(settings_menu, tearoff=0)
        self._auto_resolve_menu_var = self._auto_resolve_var
        for label, _ms in AUTO_RESOLVE_OPTIONS:
            auto_resolve_menu.add_radiobutton(
                label=label, variable=self._auto_resolve_menu_var,
                command=self._on_auto_resolve_change)
        settings_menu.add_cascade(label="Auto-resolve interval",
                                  menu=auto_resolve_menu)
        self._menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = tk.Menu(self._menubar, tearoff=0)
        help_menu.add_command(label="About mac-changer",
                              command=self._show_about)
        help_menu.add_command(label="Open config folder",
                              command=self._open_config_folder)
        self._menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=self._menubar)

    def _refresh_iface_menu(self):
        ifaces = mac_tools.get_available_interfaces()
        if not ifaces:
            ifaces = ["lo"]
        self._iface_menu.delete(0, "end")
        current = self.iface_menu.get()
        for iface in ifaces:
            self._iface_menu.add_command(
                label=iface,
                command=lambda i=iface: self._select_interface(i))
        if current and current in ifaces:
            self._iface_menu_var.set(current)

    def _select_interface(self, iface):
        self.iface_menu.set(iface)
        self._on_config_changed()

    def _bind_shortcuts(self):
        self.bind_all("<Control-i>", lambda _e: self._import_list())
        self.bind_all("<Control-e>", lambda _e: self._export_list())
        self.bind_all("<Control-s>", lambda _e: self._save_list())
        self.bind_all("<Control-a>", lambda _e: self._add_mac_row())
        self.bind_all("<Control-q>", lambda _e: self.on_close())
        self.bind_all("<Control-Up>", lambda _e: self._move_selected(-1))
        self.bind_all("<Control-Down>", lambda _e: self._move_selected(1))
        self.bind_all("<Control-Shift-A>", lambda _e: self._select_all())
        self.bind_all("<Control-Shift-N>", lambda _e: self._select_none())
        self.bind_all("<Delete>", lambda _e: self._delete_selected())
        self.bind_all("<Control-f>", lambda _e: self._focus_filter())

    def _focus_filter(self):
        self.filter_entry.focus_set()
        self.filter_entry.select_range(0, "end")

    def _show_about(self):
        from tkinter import messagebox
        messagebox.showinfo(
            "About mac-changer",
            f"mac-changer v{__version__}\n\n"
            "Interval MAC rotation with connectivity verification.\n"
            "Optionally rotates hostname alongside MAC.\n\n"
            "Uses fisheye-gui's mac_tools library.\n"
            "https://github.com/928dk/mac-changer")

    def _open_config_folder(self):
        import subprocess
        from rotation_engine import _invoking_home
        config_dir = os.path.join(_invoking_home(), ".config", "mac-changer")
        try:
            subprocess.Popen(["xdg-open", config_dir])
        except Exception as e:
            self.log(f"[!] Could not open config folder: {e}")

    def _move_selected(self, direction):
        if not self.mac_rows:
            return
        focused = self.focus_get()
        idx = None
        for i, r in enumerate(self.mac_rows):
            if focused in self._row_widgets(r):
                idx = i
                break
        if idx is None:
            self.log("[!] Click a MAC row first, then use Move up/down")
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.mac_rows):
            return
        self.mac_rows[idx], self.mac_rows[new_idx] = (
            self.mac_rows[new_idx], self.mac_rows[idx])
        self._reindex_rows()
        self._on_config_changed()

    def _delete_selected(self):
        to_remove = [r for r in self.mac_rows if bool(r["check"].get())]
        if not to_remove:
            self.log("[i] No checked rows to delete")
            return
        for r in to_remove:
            self._remove_mac_row(r["remove_btn"])

    # ---- UI construction ---------------------------------------------------

    def _build_ui(self):
        pad = 8

        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=pad, pady=(pad, 4))

        ctk.CTkLabel(top, text="Interface").grid(row=0, column=0, padx=6, pady=6)
        self.iface_menu = self._tt(
            ctk.CTkOptionMenu(top, values=[],
                              command=lambda _v: self._on_config_changed()),
            "Network interface whose MAC is rotated")
        self.iface_menu.grid(row=0, column=1, padx=6, pady=6)
        self._tt(ctk.CTkButton(top, text="Refresh", width=80,
                               command=self._refresh_interfaces),
                 "Re-detect available network interfaces").grid(
            row=0, column=2, padx=6, pady=6)
        ctk.CTkLabel(top, text="Current MAC:").grid(row=0, column=3, padx=6, pady=6)
        self.cur_mac_label = ctk.CTkLabel(top, text="—", width=150, anchor="w")
        self.cur_mac_label.grid(row=0, column=4, padx=6, pady=6)
        self.loaded_label = ctk.CTkLabel(top, text="", anchor="w",
                                          text_color="gray")
        self.loaded_label.grid(row=0, column=5, padx=6, pady=6)

        ctk.CTkLabel(self, text="MAC list (tick = rotate, FW = firewall allow)").pack(
            anchor="w", padx=pad + 4)
        self.mac_header = ctk.CTkFrame(self)
        self.mac_header.pack(fill="x", padx=pad, pady=(4, 0))
        self.mac_frame = SafeScrollableFrame(self,
                                             corner_radius=0, border_width=0)
        self.mac_frame.pack(fill="both", expand=True, padx=pad, pady=(0, 4))
        self._build_header_bar()
        mac_actions = ctk.CTkFrame(self)
        mac_actions.pack(fill="x", padx=pad + 4, pady=2)
        self._tt(ctk.CTkButton(mac_actions, text="+ Add MAC", width=100,
                               command=self._add_mac_row),
                 "Add a new MAC address to the rotation list").grid(
            row=0, column=0, padx=(0, 6), pady=2)
        self._tt(ctk.CTkButton(mac_actions, text="Discover", width=90,
                               command=self._discover_devices),
                 "Discover devices on the local network (ARP sweep + DHCP cache)").grid(
            row=0, column=1, padx=(0, 6), pady=2)
        self.filter_entry = self._tt(
            ctk.CTkEntry(mac_actions, width=200,
                         placeholder_text="Filter MAC / host…",
                         textvariable=self.filter_var),
            "Filter the list by MAC or hostname text (Ctrl+F)")
        self.filter_entry.grid(row=0, column=2, padx=(6, 0), pady=2)
        self.filter_entry.bind("<KeyRelease>", self._apply_filter)

        mid = ctk.CTkFrame(self)
        mid.pack(fill="x", padx=pad, pady=4)
        ctk.CTkLabel(mid, text="Interval").grid(row=0, column=0, padx=6, pady=6)
        self.interval_menu = self._tt(
            ctk.CTkOptionMenu(mid, values=[i[0] for i in INTERVALS],
                              variable=self.interval_var,
                              command=lambda _v: self._on_config_changed()),
            "How often the MAC rotates")
        self.interval_menu.grid(row=0, column=1, padx=6, pady=6)
        ctk.CTkLabel(mid, text="Custom (s):").grid(row=0, column=2, padx=6, pady=6)
        self.custom_entry = self._tt(
            ctk.CTkEntry(mid, width=90),
            "Custom interval in seconds when 'custom' is selected")
        self.custom_entry.grid(row=0, column=3, padx=6, pady=6)
        self.custom_entry.insert(0, str(self.cfg["interval_seconds"]))

        ctk.CTkLabel(mid, text="Down delay:").grid(row=1, column=0, padx=6, pady=6)
        self.down_delay_var = ctk.StringVar(value=self._delay_label_for(
            self.cfg.get("down_delay_seconds", 0)))
        self.down_delay_menu = self._tt(
            ctk.CTkOptionMenu(mid, values=[label for label, _secs in DOWN_DELAY_OPTIONS],
                              variable=self.down_delay_var,
                              command=lambda _v: self._on_config_changed()),
            "Seconds to keep the link down before reconnecting")
        self.down_delay_menu.grid(row=1, column=1, padx=6, pady=6)
        ctk.CTkLabel(mid, text="Link down before reconnect",
                     text_color="gray").grid(row=1, column=2, padx=6, pady=6)

        self.hostname_var = ctk.BooleanVar(value=self.cfg.get("hostname_enabled", False))
        self.hostname_chk = self._tt(
            ctk.CTkCheckBox(mid, text="Rotate hostname",
                           variable=self.hostname_var,
                           command=self._on_config_changed),
            "Change system hostname alongside MAC address")
        self.hostname_chk.grid(row=2, column=0, columnspan=2, padx=6, pady=6, sticky="w")
        ctk.CTkLabel(mid, text="Pattern:").grid(row=2, column=2, padx=6, pady=6)
        self.hostname_pattern_entry = self._tt(
            ctk.CTkEntry(mid, width=180,
                        placeholder_text="device-{mac_suffix}"),
            "Hostname pattern: {mac}, {mac_suffix}, {mac_hex}")
        self.hostname_pattern_entry.grid(row=2, column=3, padx=6, pady=6, sticky="w")
        self.hostname_pattern_entry.insert(0, self.cfg.get("hostname_pattern", "device-{mac_suffix}"))
        self.hostname_pattern_entry.bind("<KeyRelease>", lambda _e: self._on_config_changed())

        ctrl = ctk.CTkFrame(self)
        ctrl.pack(fill="x", padx=pad, pady=4)
        self.toggle_btn = self._tt(
            ctk.CTkButton(ctrl, text="Start", width=120,
                          command=self._toggle_rotation),
            "Start interval MAC rotation / Stop rotation while running")
        self.toggle_btn.pack(side="left", padx=6, pady=6)
        self._tt(ctk.CTkButton(ctrl, text="Restore original", width=140,
                               command=self._restore_original),
                 "Restore the interface's original MAC address").pack(
            side="left", padx=6, pady=6)
        self.status_label = ctk.CTkLabel(ctrl, text="Stopped", text_color="gray")
        self.status_label.pack(side="right", padx=10)

        ctk.CTkLabel(self, text="Log").pack(anchor="w", padx=pad + 4)
        self.log_box = ctk.CTkTextbox(self, state="disabled", height=200)
        self.log_box.pack(fill="both", expand=True, padx=pad, pady=(2, pad))

    # ---- Data wiring --------------------------------------------------------

    def _build_header_bar(self):
        for i, (_key, _label, width) in enumerate(COLUMNS):
            w = self._col_widths.get(_key, width)
            self.mac_header.grid_columnconfigure(i, minsize=w)
            self.mac_frame.grid_columnconfigure(i, minsize=w)
        ctk.CTkLabel(self.mac_header, text=COLUMNS[0][1],
                     width=self._col_widths.get("rotate", 36),
                     anchor="center").grid(row=0, column=0, padx=6, pady=2)
        for i, (key, label, width) in enumerate(COLUMNS[1:5], start=1):
            w = self._col_widths.get(key, width)
            btn = ctk.CTkButton(self.mac_header, text=label, width=w, height=28,
                                fg_color="transparent", border_width=0,
                                corner_radius=0, anchor="w",
                                text_color=("gray10", "gray90"))
            btn.grid(row=0, column=i, padx=6, pady=2, sticky="w")
            btn.configure(command=lambda k=key: self._on_header_click(k))
            self._header_buttons[key] = self._tt(
                btn, "Sort by column; click again to toggle ▲/▼ direction")
            handle = ctk.CTkFrame(self.mac_header, width=4, height=28,
                                  fg_color="gray60", cursor="sb_h_double_arrow")
            handle.grid(row=0, column=i + 10, padx=0, pady=2, sticky="ns")
            handle.bind("<ButtonPress-1>",
                        lambda e, k=key, hi=i: self._col_resize_start(e, k, hi))
            handle.bind("<B1-Motion>",
                        lambda e, k=key, hi=i: self._col_resize_drag(e, k, hi))
        ctk.CTkLabel(self.mac_header, text="",
                     width=self._col_widths.get("remove", 36)).grid(
            row=0, column=5, padx=6, pady=2)

    def _col_resize_start(self, event, key, header_idx):
        self._col_drag_key = key
        self._col_drag_start_x = event.x_root
        self._col_drag_start_w = self._col_widths.get(key, 100)

    def _col_resize_drag(self, event, key, header_idx):
        delta = event.x_root - self._col_drag_start_x
        new_w = max(40, self._col_drag_start_w + delta)
        self._col_widths[key] = new_w
        self.mac_header.grid_columnconfigure(header_idx, minsize=new_w)
        self.mac_frame.grid_columnconfigure(header_idx, minsize=new_w)
        for row_idx in range(self.mac_frame.winfo_children().__len__()):
            try:
                child = self.mac_frame.winfo_children()[row_idx]
                child.grid_columnconfigure(header_idx, minsize=new_w)
            except Exception:
                pass

    def _on_header_click(self, key):
        if key not in SORTABLE_COLUMNS:
            return
        if self._sort_col == key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = key
            self._sort_reverse = False
        self._sort_rows(key, reverse=self._sort_reverse)

    def _update_sort_indicator(self):
        for key, btn in self._header_buttons.items():
            label = COLUMN_LABELS[key]
            if key == self._sort_col:
                label = f"{label} {'▲' if not self._sort_reverse else '▼'}"
            btn.configure(text=label)

    def _active_interfaces(self) -> list:
        """Return all non-loopback interfaces for DHCP sniffing."""
        ifaces = mac_tools.get_available_interfaces()
        return [i for i in ifaces if i != "lo"]

    def _auto_resolve_label_for(self, ms) -> str:
        for label, val in AUTO_RESOLVE_OPTIONS:
            if val == ms:
                return label
        return "60 s"

    def _auto_resolve_ms_for(self, label) -> int:
        for l, val in AUTO_RESOLVE_OPTIONS:
            if l == label:
                return val
        return 60_000

    def _on_dhcp_toggle(self):
        enabled = self._dhcp_sniffer_var.get()
        self.cfg["dhcp_hostnames_enabled"] = enabled
        save_config(self.cfg)
        if enabled:
            ifaces = self._active_interfaces()
            if ifaces and (self._dhcp_sniffer is None or
                           not self._dhcp_sniffer.is_alive()):
                self._dhcp_sniffer = start_dhcp_sniffer(
                    ifaces, log_cb=self._log_threadsafe)
                self.log("[*] DHCP sniffer started")
        else:
            if self._dhcp_sniffer and hasattr(self._dhcp_sniffer, '_dhcp_stop'):
                self._dhcp_sniffer._dhcp_stop.set()
                self.log("[*] DHCP sniffer stopped")
            self._dhcp_sniffer = None

    def _on_auto_resolve_change(self):
        label = self._auto_resolve_var.get()
        ms = self._auto_resolve_ms_for(label)
        self.cfg["auto_resolve_interval_ms"] = ms
        save_config(self.cfg)
        if self._auto_resolve_id is not None:
            self.after_cancel(self._auto_resolve_id)
            self._auto_resolve_id = None
        if ms > 0:
            self._start_auto_resolve()
            self.log(f"[*] Auto-resolve interval set to {label}")
        else:
            self.log("[*] Auto-resolve disabled")

    def _start_auto_resolve(self):
        """Start periodic auto-resolution of hostnames from DHCP cache."""
        if self._auto_resolve_id is not None:
            return
        self._auto_resolve_tick()

    def _auto_resolve_tick(self):
        """Periodically resolve hostnames from DHCP cache (no manual click needed)."""
        import threading
        interval_ms = self._auto_resolve_ms_for(self._auto_resolve_var.get())
        if interval_ms <= 0:
            return
        if self.worker and self.worker.is_alive():
            self._auto_resolve_id = self.after(interval_ms,
                                               self._auto_resolve_tick)
            return
        macs = [r["entry"].get().strip() for r in self.mac_rows
                if r["entry"].get().strip()]
        if macs:
            threading.Thread(target=self._auto_resolve_worker,
                             args=(macs,), daemon=True).start()
        self._auto_resolve_id = self.after(interval_ms,
                                           self._auto_resolve_tick)

    def _auto_resolve_worker(self, macs):
        try:
            names, last_seen = resolve_hostnames_live(macs, known_map=self._hostnames)
        except Exception:
            return
        self.after(0, lambda: self._apply_resolved(names, last_seen))

    def _refresh_interfaces(self):
        ifaces = mac_tools.get_available_interfaces()
        if not ifaces:
            ifaces = ["lo"]
        self.iface_menu.configure(values=ifaces)
        if self.cfg.get("interface") in ifaces:
            self.iface_menu.set(self.cfg["interface"])
        else:
            self.iface_menu.set(ifaces[0])
        self._refresh_iface_menu()

    def _populate_config(self):
        for entry in self.cfg.get("macs", []):
            mac = entry.get("mac", "") if isinstance(entry, dict) else str(entry)
            enabled = entry.get("enabled", True) if isinstance(entry, dict) else True
            hostname = entry.get("hostname", "") if isinstance(entry, dict) else ""
            last_seen_at = entry.get("last_seen_at", "") if isinstance(entry, dict) else ""
            firewall_allow = (entry.get("firewall_allow", None)
                              if isinstance(entry, dict) else None)
            self._add_mac_row(mac=mac, enabled=enabled,
                              hostname=hostname, last_seen_at=last_seen_at,
                              firewall_allow=firewall_allow)
        if not self.mac_rows and self.cfg.get("macs"):
            self.log("[!] Config MAC list could not be loaded (invalid format)")
        self.log(f"[i] {loaded_macs_summary(self.cfg)}")
        if not self.mac_rows:
            self._show_empty_state()
        self._update_current_mac()

    def _hostname_text(self, mac, hostname) -> str:
        if hostname:
            return hostname
        return "(no hostname)" if mac else ""

    def _last_seen_text(self, mac, last_seen_at) -> str:
        if last_seen_at:
            return last_seen_at
        return "never" if mac else ""

    def _add_mac_row(self, mac="", enabled=True, hostname="", last_seen_at="",
                     firewall_allow=None):
        self._hide_empty_state()
        mac = mac_tools.normalize_mac(mac)
        if not hostname:
            hostname = self._hostnames.get(mac, "")
        if not last_seen_at:
            last_seen_at = self._seen.get(mac, "")
        if firewall_allow is None:
            firewall_allow = self._fw.get(mac, True)
        row = len(self.mac_rows)
        chk = ctk.CTkCheckBox(self.mac_frame, text="")
        chk.grid(row=row, column=0, padx=6, pady=4)
        chk.select() if enabled else chk.deselect()
        entry = ctk.CTkEntry(self.mac_frame, width=self._col_widths.get("mac", 200),
                             placeholder_text="AA:BB:CC:DD:EE:FF")
        entry.grid(row=row, column=1, padx=6, pady=4)
        if mac:
            entry.insert(0, mac)
        host_lbl = ctk.CTkLabel(self.mac_frame, text=self._hostname_text(mac, hostname),
                                width=self._col_widths.get("hostname", 180), anchor="w")
        host_lbl.grid(row=row, column=2, padx=6, pady=4)
        last_lbl = ctk.CTkLabel(self.mac_frame, text=self._last_seen_text(mac, last_seen_at),
                                width=self._col_widths.get("last_seen", 150), anchor="w",
                                text_color="gray")
        last_lbl.grid(row=row, column=3, padx=6, pady=4)
        fw = ctk.CTkCheckBox(self.mac_frame, text="")
        fw.grid(row=row, column=4, padx=6, pady=4)
        fw.select() if firewall_allow else fw.deselect()
        btn = ctk.CTkButton(self.mac_frame, text="✕", width=30, fg_color="#8a2f2f",
                            hover_color="#a04040")
        btn.grid(row=row, column=5, padx=6, pady=4)
        btn.configure(command=lambda b=btn: self._remove_mac_row(b))
        row_data = {"check": chk, "entry": entry, "hostname_lbl": host_lbl,
                    "last_lbl": last_lbl, "fw_chk": fw, "remove_btn": btn,
                    "hostname": hostname, "last_seen_at": last_seen_at}
        entry.bind("<KeyRelease>", lambda _e: self._row_edited(row_data))
        chk.configure(command=self._on_config_changed)
        fw.configure(command=self._on_config_changed)
        self.mac_rows.append(row_data)

    def _row_widgets(self, row) -> tuple:
        return (row["check"], row["entry"], row["hostname_lbl"],
                row["last_lbl"], row["fw_chk"], row["remove_btn"])

    def _reindex_rows(self):
        for i, r in enumerate(self.mac_rows):
            for col, w in enumerate(self._row_widgets(r)):
                w.grid(row=i, column=col)

    def _destroy_all_rows(self):
        for r in self.mac_rows:
            for w in self._row_widgets(r):
                w.destroy()
        self.mac_rows.clear()

    def _row_edited(self, row):
        mac = mac_tools.normalize_mac(row["entry"].get().strip())
        if mac:
            hostname = self._hostnames.get(mac, "")
            last_seen_at = self._seen.get(mac, "")
            if hostname:
                row["hostname"] = hostname
            if last_seen_at:
                row["last_seen_at"] = last_seen_at
            if mac in self._fw:
                row["fw_chk"].select() if self._fw[mac] else row["fw_chk"].deselect()
        row["hostname_lbl"].configure(text=self._hostname_text(mac, row["hostname"]))
        row["last_lbl"].configure(text=self._last_seen_text(mac, row["last_seen_at"]))
        self._on_config_changed()

    def _row_hostname(self, row) -> str:
        return row.get("hostname", "")

    def _row_last_seen(self, row) -> str:
        return row.get("last_seen_at", "")

    def _remove_mac_row(self, remove_btn):
        for i, r in enumerate(self.mac_rows):
            if r["remove_btn"] is remove_btn:
                for w in self._row_widgets(r):
                    w.destroy()
                self.mac_rows.pop(i)
                self._reindex_rows()
                break
        self._apply_filter()
        if not self.mac_rows:
            self._show_empty_state()
        self._on_config_changed()

    def _import_list(self):
        try:
            from customtkinter import filedialog
        except ImportError:
            self.log("[!] File dialog unavailable in this customtkinter build")
            return
        path = filedialog.askopenfilename(
            title="Import MAC list",
            initialdir=self.cfg.get("last_import_dir") or None,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self.cfg["last_import_dir"] = os.path.dirname(path)
        save_config(self.cfg)
        macs = load_mac_list(path)
        if not macs:
            self.log(f"[!] No valid MACs found in {os.path.basename(path)}")
            return
        existing = {mac_tools.normalize_mac(r["entry"].get().strip())
                    for r in self.mac_rows if r["entry"].get().strip()}
        added = 0
        skipped = 0
        for item in macs:
            mac = item["mac"] if isinstance(item, dict) else item
            if mac in existing:
                skipped += 1
                continue
            hostname = item.get("hostname", "") if isinstance(item, dict) else ""
            fw = item.get("firewall_allow") if isinstance(item, dict) else None
            self._add_mac_row(mac=mac, enabled=True,
                              hostname=hostname, firewall_allow=fw)
            existing.add(mac)
            added += 1
        self.cfg["macs"] = self._collect_row_data()
        self.log(f"[i] Imported {added} MAC(s) from {os.path.basename(path)}"
                 + (f", {skipped} duplicate(s) skipped" if skipped else ""))
        self.log(f"[i] {loaded_macs_summary(self.cfg)}")
        if self.mac_rows:
            self._hide_empty_state()
        self._on_config_changed()

    def _export_list(self):
        try:
            from customtkinter import filedialog
        except ImportError:
            self.log("[!] File dialog unavailable in this customtkinter build")
            return
        path = filedialog.asksaveasfilename(
            title="Export MAC list",
            initialdir=self.cfg.get("last_export_dir") or None,
            defaultextension=".json",
            initialfile="mac-list.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self.cfg["last_export_dir"] = os.path.dirname(path)
        save_config(self.cfg)
        macs = [r["entry"].get() for r in self.mac_rows]
        if export_mac_list(path, macs):
            self.log(f"[i] Exported {len(macs)} MAC(s) to {os.path.basename(path)}")
        else:
            self.log("[!] Export failed")

    def _scan_registered(self):
        import threading
        self.log("[*] Scanning registered devices (ARP/neighbor table)…")
        t = threading.Thread(target=self._scan_worker, daemon=True)
        t.start()

    def _scan_worker(self):
        def log(text):
            self._log_threadsafe(text)
        try:
            seen, total, _results = scan_registered(active=False, log_cb=log)
            self._log_threadsafe(
                f"[{'ok' if total else '!!'}] {seen} of {total} registered devices seen")
        except Exception as e:
            self._log_threadsafe(f"[!] Scan error: {e}")

    # ---- List enrichment -----------------------------------------------------

    def _collect_row_data(self):
        rows = []
        for r in self.mac_rows:
            raw = r["entry"].get().strip()
            if not raw:
                continue
            rows.append({
                "mac": mac_tools.normalize_mac(raw),
                "enabled": bool(r["check"].get()),
                "hostname": self._row_hostname(r),
                "last_seen_at": self._row_last_seen(r),
                "firewall_allow": bool(r["fw_chk"].get()),
            })
        return rows

    def _persist_config(self):
        self.cfg["macs"] = self._collect_row_data()
        save_config(self.cfg)

    def _save_list(self):
        rows = self._collect_row_data()
        changed = merge_register(rows)
        if changed:
            self.log(f"[i] Saved list: {changed} register entrie(s) updated/inserted")
            self._fw = firewall_map()
        else:
            self.log("[!] Nothing to save (no valid MAC rows)")
        self.log(f"[i] {loaded_macs_summary(self.cfg)}")
        self._on_config_changed()

    def _sort_rows(self, key, reverse=False):
        if key not in SORTABLE_COLUMNS:
            self.log(f"[!] Unknown sort column: {key}")
            return
        data = []
        for r in self.mac_rows:
            data.append({"mac": mac_tools.normalize_mac(r["entry"].get().strip()),
                         "enabled": bool(r["check"].get()),
                         "hostname": self._row_hostname(r),
                         "last_seen_at": self._row_last_seen(r),
                         "firewall_allow": bool(r["fw_chk"].get())})
        if key == "mac":
            data.sort(key=lambda d: d["mac"], reverse=reverse)
        elif key == "fw":
            data.sort(key=lambda d: not d["firewall_allow"], reverse=reverse)
        else:  # hostname / last_seen: blanks always sort last in both directions
            def field(d):
                return (d[key] or "").lower()
            non_blank = [d for d in data if field(d)]
            blank = [d for d in data if not field(d)]
            non_blank.sort(key=field, reverse=reverse)
            data = non_blank + blank
        self._destroy_all_rows()
        for d in data:
            self._add_mac_row(mac=d["mac"], enabled=d["enabled"],
                              hostname=d["hostname"], last_seen_at=d["last_seen_at"],
                              firewall_allow=d["firewall_allow"])
        self._sort_col = key
        self._sort_reverse = reverse
        self._update_sort_indicator()
        self.log(f"[i] Sorted list by {COLUMN_LABELS.get(key, key)}"
                 + (" (desc)" if reverse else ""))
        self._apply_filter()
        self._on_config_changed()

    def _select_all(self):
        for r in self.mac_rows:
            r["check"].select()
        self._on_config_changed()

    def _select_none(self):
        for r in self.mac_rows:
            r["check"].deselect()
        self._on_config_changed()

    def _clear_list(self):
        if self.worker and self.worker.is_alive():
            self.log("[!] Stop rotation before clearing the list")
            return
        if not self.mac_rows:
            self.log("[i] List is already empty")
            return
        count = len(self.mac_rows)
        self._destroy_all_rows()
        self.cfg["macs"] = []
        save_config(self.cfg)
        self.log(f"[*] Cleared {count} MACs from in-memory list")
        self.loaded_label.configure(text="0 MACs loaded")
        self._on_config_changed()

    def _new_list(self):
        if self.worker and self.worker.is_alive():
            self.log("[!] Stop rotation before creating a new list")
            return
        if self.mac_rows:
            from tkinter import messagebox
            if not messagebox.askyesno("New list",
                                       "Discard current list and start fresh?\n"
                                       "Unsaved changes will be lost."):
                return
        self._destroy_all_rows()
        self.cfg["macs"] = []
        save_config(self.cfg)
        try:
            os.remove(dhcp_hostnames_path())
        except OSError:
            pass
        self._hostnames.clear()
        self._fw.clear()
        self._seen.clear()
        self.loaded_label.configure(text="No MACs loaded")
        self._show_empty_state()
        self.log("[i] New list created (DHCP hostname cache cleared)")
        self._on_config_changed()

    def _show_empty_state(self):
        if self._empty_state_label is not None:
            return
        self._empty_state_label = ctk.CTkLabel(
            self.mac_frame,
            text="No MACs loaded\n\n"
                 "Import a list  (Ctrl+I)  ·  Add a MAC  (Ctrl+A)\n"
                 "or discover devices on your network  (View → Discover devices)",
            text_color="gray", justify="center", font=("", 13))
        self._empty_state_label.grid(row=0, column=0, columnspan=6,
                                     pady=80, sticky="nsew")

    def _hide_empty_state(self):
        if self._empty_state_label is not None:
            try:
                self._empty_state_label.destroy()
            except Exception:
                pass
            self._empty_state_label = None

    def _discover_devices(self):
        import threading
        self.log("[*] Discovering devices on network (ARP sweep + DHCP cache)…")
        t = threading.Thread(target=self._discover_worker, daemon=True)
        t.start()

    def _discover_worker(self):
        def log(text):
            self._log_threadsafe(text)
        try:
            devices = discover_devices(log_cb=log)
            self.after(0, lambda: self._show_discovery_results(devices))
        except Exception as e:
            self._log_threadsafe(f"[!] Discovery error: {e}")

    def _show_discovery_results(self, devices):
        if not devices:
            self.log("[i] No devices discovered")
            return
        existing = {mac_tools.normalize_mac(r["entry"].get().strip())
                    for r in self.mac_rows if r["entry"].get().strip()}
        dlg = ctk.CTkToplevel(self)
        dlg.title("Discover devices")
        dlg.geometry("520x480")
        dlg.transient(self)
        dlg.grab_set()
        ctk.CTkLabel(dlg, text=f"Found {len(devices)} device(s)",
                     font=("", 14, "bold")).pack(padx=10, pady=(10, 4))
        scroll = ctk.CTkScrollableFrame(dlg, corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        vars_list = []
        for dev in devices:
            mac = dev["mac"]
            hostname = dev.get("hostname", "")
            source = dev.get("source", "")
            already = mac in existing
            var = ctk.BooleanVar(value=not already)
            vars_list.append((var, mac))
            row = ctk.CTkFrame(scroll)
            row.pack(fill="x", padx=4, pady=2)
            chk = ctk.CTkCheckBox(row, text="", variable=var, width=30)
            chk.pack(side="left", padx=(4, 8))
            if already:
                chk.configure(state="disabled")
            mac_lbl = ctk.CTkLabel(row, text=mac, width=160, anchor="w",
                                   font=("Courier", 12))
            mac_lbl.pack(side="left", padx=4)
            host_lbl = ctk.CTkLabel(row, text=hostname or "(unknown)",
                                    width=160, anchor="w", text_color="gray")
            host_lbl.pack(side="left", padx=4)
            src_lbl = ctk.CTkLabel(row, text=source, width=40, anchor="w",
                                   text_color="gray")
            src_lbl.pack(side="left", padx=4)
            if already:
                src_lbl.configure(text="in list")

        def add_selected():
            added = 0
            for var, mac in vars_list:
                if var.get() and mac not in existing:
                    self._add_mac_row(mac=mac, enabled=True,
                                      hostname=dict(devices).get(mac, ""))
                    existing.add(mac)
                    added += 1
            if added:
                self.log(f"[i] Added {added} device(s) from discovery")
                self._hide_empty_state()
                self._persist_config()
            self._on_config_changed()
            dlg.destroy()

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(btn_frame, text="Add selected", width=120,
                      command=add_selected).pack(side="left", padx=4)
        ctk.CTkButton(btn_frame, text="Cancel", width=80,
                      fg_color="gray50", hover_color="gray40",
                      command=dlg.destroy).pack(side="left", padx=4)

    def _apply_filter(self, _event=None):
        query = self.filter_var.get().strip().lower()
        for r in self.mac_rows:
            mac = r["entry"].get().strip().lower()
            host = self._row_hostname(r).lower()
            if query and query not in mac and query not in host:
                self._set_row_visible(r, False)
            else:
                self._set_row_visible(r, True)

    def _set_row_visible(self, r, visible):
        for w in self._row_widgets(r):
            if visible:
                w.grid()
            else:
                w.grid_remove()

    def _resolve_hostnames(self):
        import threading
        macs = [r["entry"].get().strip() for r in self.mac_rows
                if r["entry"].get().strip()]
        if not macs:
            self.log("[!] No MACs to resolve")
            return
        self.log(f"[*] Resolving hostnames for {len(macs)} MAC(s)…")
        threading.Thread(target=self._resolve_worker, args=(macs,), daemon=True).start()

    def _resolve_worker(self, macs):
        try:
            names, last_seen = resolve_hostnames_live(macs, known_map=self._hostnames)
        except Exception as e:
            self._log_threadsafe(f"[!] Hostname resolution error: {e}")
            return
        self.after(0, lambda: self._apply_resolved(names, last_seen))

    def _apply_resolved(self, names, last_seen=None):
        if last_seen is None:
            last_seen = {}
        updated = 0
        seen_updated = 0
        for r in self.mac_rows:
            mac = mac_tools.normalize_mac(r["entry"].get().strip())
            if not mac:
                continue
            name = names.get(mac, "")
            if name and name != self._row_hostname(r):
                r["hostname"] = name
                r["hostname_lbl"].configure(text=self._hostname_text(mac, name))
                self._hostnames[mac] = name
                updated += 1
            ts = last_seen.get(mac, "")
            if ts and ts != r.get("last_seen_at", ""):
                r["last_seen_at"] = ts
                r["last_lbl"].configure(text=self._last_seen_text(mac, ts))
                self._seen[mac] = ts
                seen_updated += 1
        if updated or seen_updated:
            parts = []
            if updated:
                parts.append(f"{updated} hostname(s)")
            if seen_updated:
                parts.append(f"{seen_updated} last-seen(s)")
            self.log(f"[i] Resolved {', '.join(parts)}")
            if seen_updated:
                from rotation_engine import save_seen_state
                save_seen_state(self._seen)
            self._persist_config()
        else:
            self.log("[i] No new hostnames resolved")
        self._on_config_changed()

    # ---- Rotation controls ---------------------------------------------------

    def _collect_macs(self):
        macs = []
        for r in self.mac_rows:
            raw = r["entry"].get().strip()
            if raw:
                macs.append((bool(r["check"].get()), mac_tools.normalize_mac(raw)))
        return macs

    def _selected_interval(self) -> int:
        label = self.interval_var.get()
        for name, secs in INTERVALS:
            if name == label:
                if secs > 0:
                    return secs
                try:
                    return max(int(self.custom_entry.get().strip() or "0"), 1)
                except ValueError:
                    return DEFAULT_INTERVAL
        return DEFAULT_INTERVAL

    def _delay_label_for(self, seconds) -> str:
        try:
            seconds = max(int(seconds), 0)
        except (TypeError, ValueError):
            return "Off"
        for label, secs in DOWN_DELAY_OPTIONS:
            if secs == seconds:
                return label
        return "Off"

    def _selected_down_delay(self) -> int:
        label = self.down_delay_var.get()
        for name, secs in DOWN_DELAY_OPTIONS:
            if name == label:
                return secs
        return 0

    def _toggle_rotation(self):
        if self.worker and self.worker.is_alive():
            self.worker.stop()
            self.toggle_btn.configure(text="Start")
            self.status_label.configure(text="Stopping…")
            return
        iface = self.iface_menu.get()
        macs = self._collect_macs()
        if not macs:
            self.log("[!] Add at least one MAC first")
            return
        enabled = [m for (en, m) in macs if en]
        if not enabled:
            self.log("[!] No enabled MACs (tick at least one)")
            return
        bad = [m for (en, m) in macs if not mac_tools.is_valid_mac(m)]
        if bad:
            self.log(f"[!] Invalid MACs ignored: {', '.join(bad)}")

        self.cfg["interface"] = iface
        self.cfg["macs"] = self._collect_row_data()
        self.cfg["interval_seconds"] = self._selected_interval()
        self.cfg["interval_label"] = self.interval_var.get()
        self.cfg["down_delay_seconds"] = self._selected_down_delay()
        self.cfg["hostname_enabled"] = self.hostname_var.get()
        self.cfg["hostname_pattern"] = self.hostname_pattern_entry.get().strip() or "device-{mac_suffix}"
        save_config(self.cfg)

        self.log(f"[*] {loaded_macs_summary(self.cfg)}")
        self.worker = RotationWorker(
            iface, macs, self._selected_interval(),
            log_cb=self._log_threadsafe,
            done_cb=self._rotation_done,
            down_delay=self._selected_down_delay(),
            hostname_enabled=self.hostname_var.get(),
            hostname_pattern=self.cfg["hostname_pattern"],
        )
        self.toggle_btn.configure(text="Stop")
        self.status_label.configure(text="Running")
        self.worker.start()

    def _rotation_done(self):
        def _finish():
            self.toggle_btn.configure(text="Start")
            self.status_label.configure(text="Stopped")
            self._update_current_mac()
        self.after(0, _finish)

    def _restore_original(self):
        if self.worker and self.worker.is_alive():
            self.log("[!] Stop rotation before restoring")
            return
        iface = self.iface_menu.get()
        ok, msg = mac_tools.change_mac_restore(iface)
        self.log(f"[{'ok' if ok else '!!'}] restore: {msg}")
        self._update_current_mac()

        if self.hostname_var.get():
            from rotation_engine import get_hostname, set_hostname, restart_mdns
            original = load_original_hostname()
            if not original:
                original = get_hostname()
            if original:
                self.log(f"[*] Restoring hostname to {original}")
                h_ok, h_msg = set_hostname(original)
                self.log(f"[{'ok' if h_ok else '!!'}] hostname: {h_msg}")
                if h_ok:
                    mdns_ok, mdns_msg = restart_mdns()
                    self.log(f"[{'ok' if mdns_ok else '!!'}] {mdns_msg}")

    # ---- Logging & status ---------------------------------------------------

    def _log_threadsafe(self, text: str):
        try:
            self.after(0, lambda: self.log(text))
        except RuntimeError:
            pass

    def log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self._file_logger.info(text)
        self._update_current_mac()

    def _update_current_mac(self):
        iface = self.iface_menu.get()
        ok, mac = mac_tools.get_current_mac(iface)
        self.cur_mac_label.configure(text=mac if ok else "—")
        try:
            self.loaded_label.configure(text=loaded_macs_summary(self.cfg))
        except Exception:
            pass

    def _on_config_changed(self):
        self._update_current_mac()

    def on_close(self):
        if self._auto_resolve_id is not None:
            self.after_cancel(self._auto_resolve_id)
            self._auto_resolve_id = None
        if self.worker and self.worker.is_alive():
            self.worker.stop()
            self.worker.join(timeout=2)
        self.cfg["window_geometry"] = self.geometry()
        self.cfg["column_widths"] = dict(self._col_widths)
        save_config(self.cfg)
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    smoke = "--smoke" in argv

    app = MacChangerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    if smoke:
        app.after(1500, app.on_close)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
