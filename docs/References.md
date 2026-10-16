# References

## Reused Code
| Reference | Path | Notes |
|-----------|------|-------|
| `lib/mac_tools.py` | `~/projects/Client/fisheye-gui/lib/mac_tools.py` | MAC ops library (change, backup, restore, probe, ping). Imported via `sys.path`; **unmodified**. |
| `fisheye-gui` | `~/projects/Client/fisheye-gui/` | Parent app providing the reusable library and venv/launch patterns. |
| `flow_database.sqlite` | `~/projects/Client/data/flow_database.sqlite` | Shared `mac_backups` table used for backup/restore. |

## Upstream / Docs
- CustomTkinter: https://customtkinter.tcl-tk.com/
- scapy: https://scapy.readthedocs.io/
- Project Template: `~/Project_template.md`
- Spec framework: `.opencode/skills/system-spec-kit/` (`validate.sh`)

## Prior Specs
- `054-mac-tools` — MAC tools feature in fisheye-gui
- `055-fisheye-gui` — fisheye-gui app
- `066-mac-changer` — this project's spec packet
