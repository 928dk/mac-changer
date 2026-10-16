#!/usr/bin/env bash
set -euo pipefail

# mac-changer root launcher: ensures root + venv + deps, then starts the app.
# Re-runs itself under pkexec (sudo fallback) when not already root.

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/src/mac_changer.py"
VENV="$DIR/.venv"

relaunch_as_root() {
    local display_env=""
    [[ -n "${DISPLAY:-}" ]] && display_env="DISPLAY=$DISPLAY"
    if command -v pkexec >/dev/null 2>&1; then
        echo "[*] Re-launching as root via pkexec..."
        exec env ${display_env:+$display_env} \
            XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" \
            pkexec env DISPLAY="${DISPLAY:-}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" \
            bash "$DIR/gui.sh" "$@"
    elif command -v sudo >/dev/null 2>&1; then
        echo "[*] pkexec not found — re-launching as root via sudo..."
        exec sudo -E env ${display_env:+$display_env} \
            XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" bash "$DIR/gui.sh" "$@"
    else
        echo "[!] Root required but neither pkexec nor sudo is available." >&2
        exit 1
    fi
}

if [ "$(id -u)" -ne 0 ]; then
    relaunch_as_root "$@"
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] Could not acquire root privileges. MAC changes require root." >&2
    exit 1
fi

echo "[*] Running as root (euid=0)."

if [ ! -d "$VENV" ]; then
    echo "[*] Creating Python virtual environment..."
    python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "[*] Checking dependencies..."
python3 -c "
import importlib.util
deps = [
    ('customtkinter', 'customtkinter'),
    ('scapy', 'scapy'),
]
missing = []
for mod, pkg in deps:
    if importlib.util.find_spec(mod) is None:
        missing.append(pkg)
if missing:
    print('Missing:', ', '.join(missing))
    import subprocess
    subprocess.check_call(['pip', 'install'] + missing)
    print('Dependencies installed.')
else:
    print('All dependencies found.')
"

echo "[*] Launching mac-changer..."
exec python3 "$APP" "$@"
