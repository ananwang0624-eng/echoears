"""🙌 Two-hand duet — 30 s

Click ▶ Run (top right). Board plugged in; run/2_apply_queue.py done once.

Setup:  left hand over the left sensor (id 3), right hand over the right (id 2).
During: move the hands independently, offset rhythms (left slow, right fast),
        so each ear hears a different voice.
Use:    evidence of binaural separation — left ear left hand, right ear right.
Re-run for more takes — just click ▶ again; every run writes a new
timestamped file, nothing is overwritten.
Output -> out/capture/<label>_<time>.npz + a manifest.json line.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="duet", seconds=30,
    note="two-hand duet: left hand slow over id 3, right fast over id 2",
))
