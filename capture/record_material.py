"""🧶 Material contrast — 30 s (quiz material)

Click ▶ Run (top right). Board plugged in; run/2_apply_queue.py done once.

Setup:  mark a fixed spot at 60 cm.
During: hard book on the mark for 10 s -> empty for 5 s -> soft sweater
        bundle on the same mark for 10 s -> away.
Use:    same distance, different reflectivity — hard faces ring loud, soft
        things are orders of magnitude quieter. Quiz: "which one was the
        sweater?"
Re-run for more takes — just click ▶ again; every run writes a new
timestamped file, nothing is overwritten.
Output -> out/capture/<label>_<time>.npz + a manifest.json line.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="material", seconds=30,
    note="material: hard book 10 s at the 60 cm mark -> empty 5 s -> sweater 10 s",
))
