"""🕳 Empty-scene baseline — 15 s

Click ▶ Run (top right). Board plugged in; run/2_apply_queue.py done once.

Setup:  clear everything within 1.5 m of the sensors; step aside yourself.
During: hold still and make sure the field of view really is empty.
Use:    noise baseline — the "empty" reference and the sigma control set.
Re-run for more takes — just click ▶ again; every run writes a new
timestamped file, nothing is overwritten.
Output -> out/capture/<label>_<time>.npz + a manifest.json line.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="empty", seconds=15,
    note="empty baseline: nothing within 1.5 m, operator out of view, still",
))
