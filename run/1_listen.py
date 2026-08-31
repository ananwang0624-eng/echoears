"""🎧 Binaural listening — 233 cm

Click ▶ Run (top right). Press Enter through the defaults, or type your own.

Needs: board plugged in, headphones on.
Boot takes ~20 s (flash + phase calibration), then sound starts.

Left temple → left ear, right temple → right ear (two sensors, 4 channels,
20 Hz). Range is over two metres — walk in from across the room.

First run? Click run/2_apply_queue.py first to install the meas queue.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import (LIVE_ODR, ODR_MS, OUT, QUEUE, ask, banner,  # noqa: E402
                       ensure_py39, run_app)

ensure_py39()
banner("Binaural listening (233 cm, two sensors, 20 Hz)", "Ctrl-C to stop")

# Without the queue the range axis is silently wrong — hard stop here.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.use_queue import TOML, _current  # noqa: E402

live = _current(TOML.read_text()).get('per_sensor_defaults."icu-10201"')
if not live or Path(live).name != QUEUE.name:
    print(f"\n  ⚠️  active queue is {Path(live).name if live else 'unset'}, "
          f"not {QUEUE.name}")
    print("     Run run/2_apply_queue.py first, then come back.\n")
    raise SystemExit(1)
print(f"  ✅ queue is {QUEUE.name} (233 cm)\n")

seconds = ask("Listen for (seconds)", 60, int)
gain = ask("Volume 0.1-1.0", 0.6, float)
wav = OUT / "listen.wav"

raise SystemExit(run_app("apps/live.py", [
    "--odr", LIVE_ODR,
    "--odr-ms", ODR_MS,
    "--seconds", seconds,
    "--gain", gain,
    "--wav", wav,
]))
