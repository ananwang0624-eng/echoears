"""📚 Two objects — 30 s (one ping, two echoes)

Click ▶ Run (top right). Board plugged in; run/2_apply_queue.py done once.

Setup:  two hard-faced objects (books, cardboard) standing at 40 cm and
        90 cm, both facing the sensors.
During: first 10 s everything still; then slide the NEAR one slowly to
        60 cm and back while the far one stays put; last 5 s still again.
Use:    two echoes per ping = two voices. Targets mode holds both as a
        sustained pair; Sonar voices only the one being moved — one scene
        demonstrates both ways of listening.
Re-run for more takes — just click ▶ again; every run writes a new
timestamped file, nothing is overwritten.
Output -> out/capture/<label>_<time>.npz + a manifest.json line.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="chord", seconds=30,
    note="two objects: 40+90 cm still 10 s -> near one slides 40<->60, far still -> still 5 s",
))
