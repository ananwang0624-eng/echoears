"""🚶 Walk-up — 20 s

Click ▶ Run (top right). Board plugged in; run/2_apply_queue.py done once.

Setup:  sensors facing an open lane of ~2 m.
During: walk straight in from 2 m to 0.5 m, pause a second, back out. Twice.
Use:    a full-body target — the loud counterpart to the hand takes.
Re-run for more takes — just click ▶ again; every run writes a new
timestamped file, nothing is overwritten.
Output -> out/capture/<label>_<time>.npz + a manifest.json line.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="walk", seconds=20,
    note="walk-up: 2 m -> 0.5 m, pause 1 s, back out; twice",
))
