"""↔️ Left-right crossing — 20 s (the binaural showpiece)

Click ▶ Run (top right). Board plugged in; run/2_apply_queue.py done once.

Setup:  a clear step of space on each side, ~1 m out.
During: walk from far left to far right (~4 s), pause 2 s, walk back.
        Two passes.
Use:    the echo slides from the left ear to the right — on headphones you
        hear someone walk past.
Re-run for more takes — just click ▶ again; every run writes a new
timestamped file, nothing is overwritten.
Output -> out/capture/<label>_<time>.npz + a manifest.json line.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="cross", seconds=20,
    note="crossing: far left -> far right at ~1 m (4 s), pause 2 s, back; two passes",
))
