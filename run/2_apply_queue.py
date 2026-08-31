"""📐 Install the 233 cm meas queue

Click ▶ Run (top right). Run this on first use, or after the upstream
setup_mac_py39.py (which overwrites the plugin registry).

How it works: range = the RX instruction's listening window (SMCLK).
ODR only decides how many samples that window is cut into (340-sample cap).

This edits which file [plugins.txrot] points at in the EVK plugin registry —
it does not touch sensor firmware. The original toml is backed up as
PysonicPlugins.toml.echoears-bak; to undo everything: tools/use_queue.py restore
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import QUEUE, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("Install meas queue (233 cm)", QUEUE.name)

if not QUEUE.is_file():
    print(f"\n  queue file missing, generating it first: {QUEUE}\n")
    rc = run_app("tools/measqueue.py", [
        "write", "--range-cm", 234, "--odr", 4, "--tx", 160,
        "-o", QUEUE, "--force"])
    if rc:
        raise SystemExit(rc)

rc = run_app("tools/use_queue.py", ["set", QUEUE])
if rc == 0:
    print("\n  ✅ installed. Next: run/1_listen.py")
raise SystemExit(rc)
