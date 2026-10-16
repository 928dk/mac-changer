# Lessons Learned

## Auto-resolution + combined last-seen (v0.7.3) — 2026-08-23

- **API return type changes cascade.** Changing `resolve_hostnames_live()` from `dict` to `tuple` broke callers in `scripts/anonymize_hostnames.py`, `tests/test_vpn_connectivity.py`, and `tests/test_list_enrichment.py`. Always grep for all callers before changing return types.
- **DHCP duplicate logging is noisy.** Same MAC+hostname pair logged on every DHCP packet (dozens of times per minute). Check existing cache before logging — only log when the entry is new or changed.
- **Auto-resolution should skip during rotation.** The rotation worker changes MACs rapidly; auto-resolution during rotation would be wasteful and confusing. Check `worker.is_alive()` before resolving.

## DHCP hostname sniffer (v0.7.2) — 2026-08-23

- **Scapy sniff requires root (CAP_NET_RAW).** `socket(AF_PACKET, SOCK_RAW)` raises PermissionError without root. Mac-changer runs via pkexec, so this works in production but not in tests. Catch PermissionError and exit silently.
- **Docker/wlan bridge interfaces generate noise.** `mac_tools.get_available_interfaces()` returns all interfaces including Docker bridges (`docker0`, `br-*`) and loopback. Filter to non-loopback only for sniffing; Docker bridge DHCP is irrelevant for LAN hostname resolution.
- **DHCP option 12 = hostname, BOOTP chaddr = client MAC.** Parse BOOTP chaddr (first 6 bytes) for the client MAC, DHCP options for hostname. scapy's `DHCP` layer options list contains tuples like `("hostname", b"laptop-name")`.
- **`_log_threadsafe` crashes after app destruction.** Background threads calling `self.after()` after `app.destroy()` raise `RuntimeError: main thread is not in main loop`. Wrap in try/except.

## DNS + row move fix (v0.7.1) — 2026-08-23

- **On-link IPs have no `via` gateway.** `ip route get <on-link-ip>` returns a direct route without `via`, so `_ptr_via_router` skipped dig entirely. Always try system DNS and `getent hosts` as fallbacks.
- **dig error output looks like hostnames.** Lines starting with `;;` are dig diagnostics, not PTR records. Filter them in `_dig_reverse`.
- **`getent hosts` is a good fallback.** Reads `/etc/hosts` + NSS without depending on systemd-resolved. Works for local hostnames.

## GUI enhancements (v0.7.0) — 2026-08-23

- **`_ptr_via_router` before `socket.gethostbyaddr` for sudo context.** Under `pkexec`/`sudo`, `socket.gethostbyaddr` uses NSS which tries systemd-resolved (127.0.0.53) — disabled on this system. The router DNS path (`dig` via `/etc/resolv.conf`) works. Always try the router path first.
- **Drag handles need consistent grid across header and frame.** Column resize handles must update `grid_columnconfigure` on both `mac_header` and `mac_frame`; also update row widgets' `minsize` for existing rows.
- **File logger with `TimedRotatingFileHandler`** is simpler than manual rotation. Use `when="W0"` for weekly rotation, `backupCount=4` for 4-week retention.
- **Widget tooltip count can drift from test expectations.** When adding/removing widgets, update `smoke_100.py` `BUTTON_TIPS` and `ATTR_TIPS` dicts to match actual widget set.

## Initial build (v0.1.0) — 2026-08-01

- **Split engine from GUI early.** `rotation_engine.py` is GUI-independent so root/headless
  tests never need `customtkinter`. The engine was verified in isolation (config round-trip,
  worker loop on a synthetic dummy interface) before the GUI was smoke-tested under Xvfb.
- **`pkexec` needs a polkit agent + TTY.** In an agent-less, non-TTY shell the root GUI smoke
  via `gui.sh` hangs (exit 124) — policy `org.freedesktop.policykit.exec` is `auth_admin`.
  Verify manually from the desktop session with `./gui.sh --smoke`. The pkexec→root command
  path itself is proven by the green dummy-interface run.
- **`pkexec` resets the working directory.** Re-launching via `bash "$0"` fails after
  elevation (`./gui.sh: No such file or directory`). Always re-launch with an absolute path:
  `bash "$DIR/gui.sh"`.
- **Resolve `~` to the invoking user, not root.** Under `pkexec`/`sudo`, euid is 0, so
  `_invoking_home()` reads `PKEXEC_UID`/`SUDO_UID` to keep config at
  `~/.config/mac-changer/config.json` instead of `/root`.
- **`xvfb-run -a` beats manual backgrounding.** It manages the Xvfb lifecycle; manually
  backgrounding Xvfb hangs the shell pipe.
- **Test on a dummy interface, never a real NIC.** `ip link add macchg0 type dummy` gives a
  safe surface for `change_mac`, backup/restore, and worker-loop tests (REQ-009).
- **`dhclient` may be absent from root's PATH.** `dhcp_renew` prefers `nmcli connection down/up`
  (fully re-establishes DHCP with new MAC after a swap) and degrades gracefully to
  `nmcli device reapply` then `dhclient` when present.

## Upcoming / To Verify
- Behavior of `active_internet_probe` (scapy raw socket) when a dummy interface has no route.
- GUI thread-safety patterns under root (`after(0, …)` for all UI updates) — verified via
  `--smoke` on the desktop.

## Hover tooltips (spec 100) — 2026-08-16
- **CustomTkinter has no tooltips.** Bind `<Enter>`/`<Leave>`/`<ButtonPress>` on each widget and
  show a passive `tk.Toplevel(overrideredirect=True)`. A ~400 ms `after()` delay avoids flicker;
  cancel it on leave.
- **CTk `bind()` forwards to internal widgets.** `CTkButton`/`CTkOptionMenu`/`CTkFrame` forward
  `bind()` to their `_canvas` + `_text_label`; `CTkEntry` to its `_entry`. It works, but the
  query form `widget.bind("<Enter>")` returns the wrapper's own (empty) bind list — assert on the
  internal targets in tests, not the wrapper.
- **A "shared popup" must live at class level.** Assigning `self._tip = ...` inside a helper
  shadows the class attribute and silently creates one popup per tooltip. Use `ToolTip._tip`.
- **`winfo_exists()` raises `TclError` after `app.destroy()`** — the shared popup outlives its
  interpreter. Wrap the check in `try/except TclError` and treat it as "needs recreate".
- **Cosmetic `invalid command name …_check_if_scrollbars_needed`** prints to stderr if the app is
  destroyed while the customtkinter scrollable frame's `after` timer is pending. Non-fatal;
  surfaced only when tests call `app.update()`.
- **Testing the double-import pitfall:** patch paths via `import rotation_engine as re` (top-level)
  and stub `mc.hostname_map`/`mc.firewall_map` — `from src import rotation_engine` is a different
  module object and its patches are dead (spec 070 fix).

## Resolve hostnames fix (spec 103) — 2026-08-23
- **`resolve_hostnames_live` register-first bug**: when `known_map` (from `hostname_map()`) is
  passed, the function put all known MACs into `out` immediately and only attempted ARP +
  reverse-DNS for the `unknown` list. If every MAC had a hostname in the register, the
  function returned without any network lookup, reporting "No new hostnames resolved".
  Fix: always check ARP cache for all MACs; use live hostname when found, fall back to
  register hostname for offline devices.
