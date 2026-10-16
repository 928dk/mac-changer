# INSTALL.md

## Requirements
- Python 3.10+ (with `tkinter`)
- Linux with `iproute2` (`ip`) — required for MAC change
- Root privileges — required for `ip link set … address`
- DHCP renewal: NetworkManager (`nmcli`) or `dhclient` on PATH

## Install

### 1. Virtual environment + dependencies
The launcher does this automatically. Manually:
```bash
cd ~/projects/Client/mac-changer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Root execution
`gui.sh` uses `pkexec` (PolicyKit). On systems without PolicyKit it falls back to `sudo`.

Optional: install a polkit rule so the GUI opens without a repeated prompt (adapt username):

`/etc/polkit-1/rules.d/60-mac-changer.rules`:
```js
polkit.addRule(function(action, subject) {
  if (action.id === "org.freedesktop.policykit.exec" &&
      subject.user === "your-user" &&
      subject.isInGroup("wheel")) {
    return polkit.Result.YES;
  }
});
```
> Caution: this broadens PolicyKit execution for your user. Prefer the default prompt flow
> unless you understand the trade-off.

## Test
```bash
python -m py_compile src/mac_changer.py
bash tests/test_import.sh
# headless GUI smoke (as root):
xvfb-run -a sudo -E python3 src/mac_changer.py --smoke
# dummy-interface rotation test:
sudo bash scripts/test_dummy_rotation.sh
```

## Uninstall
- Remove `~/projects/Client/mac-changer/` and `~/.config/mac-changer/`.
- (Optional) remove the polkit rule added above.
