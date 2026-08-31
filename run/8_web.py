"""🌐 Live listening in the browser — one click

Click ▶ Run (top right); zero input needed.

It does three things:
  1. starts the web server   http://localhost:8080  (static, web/)
  2. starts the rig bridge   ws://localhost:8765    (board → WebSocket)
  3. opens the browser

Click "🔌 Live" in the page, put headphones on, listen.
The 2×2 channel grid and per-channel mixer strips are on the page;
PC cross channels are off by default — tick them to hear them.

Ctrl-C stops everything. Boot takes ~20 s (flash + phase calibration).
"""
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import (LIVE_ODR, QUEUE, REPO, banner, ensure_py39,  # noqa: E402
                       run_app)

ensure_py39()
banner("Live listening in the browser (233 cm, 2x2 channels)", "Ctrl-C to stop")


def _busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


# Double-clicked twice? The first instance is still serving — just reopen the
# page instead of fighting it for the ports.
if _busy(8765) or _busy(8080):
    print("\n  already running — just opening the page.\n")
    webbrowser.open("http://localhost:8080")
    raise SystemExit(0)

# No board plugged in? Fall back to replaying the shipped recording — the
# whole web app works identically, just from disk instead of the rig.
import glob

REPLAY = REPO / "out" / "scene233.npz"
bridge_args = []
serve_only = False
if not glob.glob("/dev/cu.usbmodem*"):
    if REPLAY.is_file():
        print(f"\n  🔌 no board — the bridge will replay a recording: {REPLAY.name}\n")
        bridge_args = ["--replay", str(REPLAY), "--odr", str(LIVE_ODR)]
    else:
        # web/data ships a browser-side replay that needs NO bridge at all —
        # a fresh clone (out/ is gitignored) must still get the page.
        print("\n  🔌 no board and no npz — serving the page only; use its built-in replay.\n")
        serve_only = True
else:
    # Same guard as 1_listen: a wrong queue gives a silently wrong range axis.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.use_queue import TOML, _current  # noqa: E402

    live = _current(TOML.read_text()).get('per_sensor_defaults."icu-10201"')
    if not live or Path(live).name != QUEUE.name:
        print(f"\n  ⚠️  active queue is {Path(live).name if live else 'unset'}, "
              f"not {QUEUE.name}")
        print("     Run run/2_apply_queue.py first, then come back.\n")
        raise SystemExit(1)
    print(f"  ✅ queue is {QUEUE.name} (233 cm)\n")

web = subprocess.Popen(
    [sys.executable, "-m", "http.server", "8080", "--directory",
     str(REPO / "web")],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(1.0)
    webbrowser.open("http://localhost:8080")
    if serve_only:
        print("  page open — press ▶ Play to hear the recording. Ctrl-C to stop.\n")
        web.wait()
        raise SystemExit(0)
    print("  page open — once the bridge prints 'live … Hz', click 'Live'.\n")
    raise SystemExit(run_app("tools/bridge.py", bridge_args))
finally:
    web.terminate()
    try:
        web.wait(timeout=5)
    except Exception:                  # noqa: BLE001
        web.kill()
