"""🔍 Inspect a recording's range profile (ASCII)

Click ▶ Run (top right). No sound — data only.

Prints each channel's energy along the range axis, before and after static
clutter removal. Pre-removal peaks at 1-3 cm are ringdown; post-removal
peaks further out are real targets.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import (ARCHIVE_ODR, SAMPLE_NPZ, ask, banner,  # noqa: E402
                       ensure_py39, run_app)

ensure_py39()
banner("Recording range profile")

npz = Path(ask("npz path", str(SAMPLE_NPZ))).expanduser()
if not npz.is_file():
    raise SystemExit(f"\n  file not found: {npz}")
odr = ask("CIC ODR of this recording", ARCHIVE_ODR, int)

raise SystemExit(run_app("apps/show.py", [npz, "--odr", odr, "--static"]))
