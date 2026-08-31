"""▶ Replay a recording — no hardware needed

Click ▶ Run (top right).

Runs the IDENTICAL audio pipeline (GrainSynth + baseline clutter removal +
stereo out) from a recorded npz. Use it with no board plugged in, or to
listen to the same take repeatedly.

Enter accepts the default hand_moving take (hand in front of the rig, 30 s).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import (ARCHIVE_ODR, OUT, SAMPLE_NPZ, ask, banner,  # noqa: E402
                       ensure_py39, run_app)

ensure_py39()
banner("Replay (no hardware)", "same audio pipeline, data from a recording")

npz = Path(ask("npz path", str(SAMPLE_NPZ))).expanduser()
if not npz.is_file():
    raise SystemExit(f"\n  file not found: {npz}")

odr = ask("CIC ODR of this recording", ARCHIVE_ODR, int)
seconds = ask("Play for (seconds, 0 = all)", 30, int)
gain = ask("Volume 0.1-1.0", 0.6, float)

args = ["--replay", npz, "--odr", odr, "--gain", gain,
        "--wav", OUT / "replay.wav"]
if seconds:
    args += ["--seconds", seconds]
raise SystemExit(run_app("apps/live.py", args))
