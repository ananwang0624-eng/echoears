"""🚪 Scene event: a door — 20 s (optional)

Click ▶ Run (top right). Board plugged in; run/2_apply_queue.py done once.

Setup:  a door or cabinet inside the 2.3 m range.
During: open it once, close it once, keep everything else still —
        stand beside the frame so your body stays out of the beam.
Use:    listening-quiz material ("what happened, by ear alone?").
Re-run for more takes — just click ▶ again; every run writes a new
timestamped file, nothing is overwritten.
Output -> out/capture/<label>_<time>.npz + a manifest.json line.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="door", seconds=20,
    note="scene event: open and close one door inside range, all else still",
))
