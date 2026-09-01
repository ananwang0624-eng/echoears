"""📐 Vendor rangefinder, other presets — Short Range etc.

Click ▶ Run (top right).

run/9 uses Long Range: built for walls at 2-5 m, near thresholds of
1600/800 counts — a palm inside 80 cm barely registers. Here you can
switch to:

  short    Short Range (default): 0.19 cm/bin, listening window
           ~16-55 cm, 200-count sweet zone ~27-41 cm; stepped-down TX
           for a shorter ringdown. Palm-friendly — keep the hand
           INSIDE ~50 cm, anything further is outside the window
  static   Static Target Rejection: the chip suppresses still
           targets, reports changes only
  default  factory defaults

Everything else matches run/9: vendor gpt firmware, TX Opt, two
pulse-echo channels, on-chip targets. txrot is evicted the same way;
run/8 flashes it back.
Ctrl-C stops. Boot ~20 s (flash).
"""
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import REPO, ask, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("Vendor rangefinder, preset switch (gpt / TX Opt / 2 ch)", "Ctrl-C to stop")


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

cfg = str(ask("Preset short / static / default", "short", str)).strip().lower()
if cfg not in ("short", "static", "default"):
    print(f"\n  ⚠️  unknown preset {cfg!r}; use short / static / default.\n")
    raise SystemExit(1)

print("  ⚠️  this flashes the vendor rangefinder over txrot —")
print("      to switch back just run run/8_web.py; it reflashes txrot.\n")

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
    raise SystemExit(run_app("tools/bridge.py", ["--rangefinder",
                                                 "--cfg", cfg]))
finally:
    web.terminate()
    try:
        web.wait(timeout=5)
    except Exception:      # noqa: BLE001
        web.kill()
