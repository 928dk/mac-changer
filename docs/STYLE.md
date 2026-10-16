# STYLE.md — Coding Standards

## General
- Python 3.10+; follow [PEP 8](https://peps.python.org/pep-0008/) (4-space indent, `snake_case`).
- No comments unless they explain *why* (not *what*).
- Type hints on all function signatures.
- Small functions; one responsibility each.

## Conventions
- App code lives in `src/`; entry point `src/mac_changer.py`.
- GUI widgets that are referenced later MUST be stored as `self.<name>` (never local-only).
- Threads may not touch the UI directly — route updates through `after(0, …)`.
- External calls (`ip`, `nmcli`, `dhclient`, scapy probe) must be wrapped in try/except
  with graceful fallbacks; never crash the rotation thread.
- Validate MAC input with `mac_tools.is_valid_mac` / `normalize_mac` before applying.

## MAC / Network Rules
- Never rotate a real NIC during tests — use the dummy interface (`macchg0`).
- `change_mac` → `dhcp_renew` → `test_connection`; on failure, log + advance to next MAC.
- Backup the original MAC before the first change of a session.

## Shell (gui.sh)
- `set -euo pipefail`; quote all expansions; forward DISPLAY/XAUTHORITY to root.
- Assert `euid == 0` before launching the app.

## Docs
- Update `docs/Changelog.md`, `docs/Session_summary.md`, and `docs/Todo.md` with each change.
- Keep `README.md`, `Spec.md`, and `Agents.md` in sync with the built app.

## Verification (before finishing changes)
1. `python -m py_compile src/mac_changer.py`
2. Import check: `python -c "from src.mac_changer import ..."`
3. Dummy-interface rotation test
4. Update docs
