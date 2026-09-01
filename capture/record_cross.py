"""↔️ Left-right crossing — 20 s (the binaural showpiece)

Click ▶ Run (top right). Board plugged in.

This shot records through the VENDOR RANGEFINDER firmware with the
Short Range preset — the exact configuration run/10 demos — so the
replayed material matches what the chip's own detector hears.
Flashing takes ~20-40 s and evicts txrot; running run/8_web.py
afterwards flashes txrot back automatically.

Setup:  a clear step of space on each side, ~1 m out.
During: walk from far left to far right (~4 s), pause 2 s, walk back.
        Two passes.
Use:    the echo slides from the left ear to the right — on headphones you
        hear someone walk past.
Re-run for more takes — just click ▶ again; every run writes a new
timestamped file, nothing is overwritten.
Output -> out/capture/<label>_<time>.npz + a manifest.json line.
Replay/export MUST use the --odr the engine prints (6, not the txrot 4).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="cross_rf", seconds=20,
    note="crossing: far left -> far right at ~1 m (4 s), pause 2 s, back; "
         "two passes (rangefinder short preset)",
    rf_cfg="short",
))
