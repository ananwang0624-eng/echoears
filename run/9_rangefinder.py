"""📏 Vendor rangefinder firmware — 2 channels + Long Range + TX Opt

Click ▶ Run (top right).

The one difference from run/8, and it matters:

  run/8  txrot firmware → 2×2 matrix (pulse-echo + cross channels),
         detection on the host
  run/9  vendor gpt firmware → 2 pulse-echo channels only, the chip
         reports targets itself

The ICU-10201 has a single algorithm slot: loading the vendor
rangefinder evicts txrot, and the cross (PC) channels disappear with
it — that is the entire cost. Switching back is automatic: run/8
reflashes txrot at startup.

What you get: the chip reports "what IS there" against an absolute
threshold — still objects keep reporting forever.

In the browser switch Mode to "Targets" to hear the chip's verdicts.
Ctrl-C stops. Boot ~20 s (flash).
"""
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import REPO, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("Vendor rangefinder (gpt / Long Range / TX Opt / 2 ch)", "Ctrl-C to stop")


def _busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if _busy(8765) or _busy(8080):
    print("\n  already running — just opening the page.\n")
    webbrowser.open("http://localhost:8080")
    raise SystemExit(0)

import glob  # noqa: E402

if not glob.glob("/dev/cu.usbmodem*"):
    print("\n  ⚠️  no board. This path needs hardware (it flashes firmware).\n")
    raise SystemExit(1)

print("  ⚠️  this flashes the vendor rangefinder over txrot —")
print("      cross (PC) channels do not exist in this mode.")
print("      To switch back just run run/8_web.py; it reflashes txrot.\n")

web = subprocess.Popen(
    [sys.executable, "-m", "http.server", "8080", "--directory",
     str(REPO / "web")],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(1.0)
    webbrowser.open("http://localhost:8080")
    print("  page open — once 'rangefinder … Hz' is printed below:")
    print("    1. hard-refresh the page (Cmd-Shift-R)")
    print("    2. click '🔌 Live' (top right)")
    print("    3. switch Mode to 'Targets'\n")
    # no --odr-ms: the Long Range sequence sets its own floor
    raise SystemExit(run_app("tools/bridge.py", ["--rangefinder"]))
finally:
    web.terminate()
    try:
        web.wait(timeout=5)
    except Exception:      # noqa: BLE001
        web.kill()
