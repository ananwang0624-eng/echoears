"""🖐 Hand push-pull — 40 s (the main demo material)

Click ▶ Run (top right). Board plugged in; run/2_apply_queue.py done once.

Setup:  rig steady, palm facing the RIGHT sensor (id 2).
During: push slowly from 1 m in to 20 cm and back, 3-4 round trips;
        spend the last 10 s waving fast.
Use:    the offline demo's main course — near = high, motion = sound.
Re-run for more takes — just click ▶ again; every run writes a new
timestamped file, nothing is overwritten.
Output -> out/capture/<label>_<time>.npz + a manifest.json line.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="hand", seconds=40,
    note="hand push-pull: 1 m <-> 20 cm, 3-4 slow round trips, last 10 s fast",
))
