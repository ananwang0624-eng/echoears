"""Shared engine for capture/record_*.py — one shot per ▷ click.

Mirrors the ultrasonic repo's capture/engine pattern: every launcher is a
few lines naming its shot; this module does the rest (py39 re-exec, queue
guard, bring-up, countdown, record via tools/record.capture, manifest
append, next-step commands). Re-running a launcher never overwrites —
each run gets a timestamped file, so another take is just another click.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "run"))

from _launcher import QUEUE, banner, ensure_py39  # noqa: E402

OUT_DIR = REPO / "out" / "capture"


def _queue_guard() -> None:
    # Wrong queue = silently wrong range axis. Same hard stop as run/1.
    from tools.use_queue import TOML, _current

    live = _current(TOML.read_text()).get('per_sensor_defaults."icu-10201"')
    if not live or Path(live).name != QUEUE.name:
        print(f"\n  ⚠️  active queue is {Path(live).name if live else 'unset'}, "
              f"not {QUEUE.name}")
        print("     Run run/2_apply_queue.py first, then come back.\n")
        raise SystemExit(1)
    print(f"  ✅ queue is {QUEUE.name} (233 cm)\n")


def record_shot(label: str, seconds: float, note: str) -> int:
    ensure_py39()
    banner(f"Capture · {label} ({seconds:.0f} s)", "Ctrl-C cancels (nothing written)")
    _queue_guard()

    # resolve BEFORE the EVK stack loads: its bootstrap chdir()s
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{label}_{time.strftime('%Y%m%d_%H%M%S')}.npz"

    from echoears.sources import LiveSource
    from tools.record import capture

    print(f"  Actions: {note}\n")
    print("[capture] bring-up (flash+calibration ~20 s) ...")
    with LiveSource() as src:
        while not src.channels:
            if not src.poll():
                time.sleep(0.02)
        print(f"[capture] ready: {len(src.channels)} channels @ {src.frame_hz:.1f} Hz")
        input("  Get in position, then Enter to record: ")
        for n in (3, 2, 1):
            print(f"  {n} ...")
            time.sleep(1.0)
        print("  ● recording")
        entry = capture(src, seconds, label, note, out)

    mf = OUT_DIR / "manifest.json"
    entries = json.loads(mf.read_text()) if mf.exists() else []
    entries.append(entry)
    mf.write_text(json.dumps(entries, ensure_ascii=False, indent=2))

    py = sys.executable
    print(f"\n[capture] saved -> {out}")
    print(f"[capture] manifest {mf} ({len(entries)} entries)\n")
    print("Next steps (optional):")
    print(f"  # listen back\n  {py} {REPO}/apps/live.py --replay {out} --odr 4")
    print(f"  # export into the web demo\n  {py} {REPO}/tools/export_web.py {out} "
          f"--odr 4 -o {REPO}/web/data/{out.stem} --title {label}")
    return 0
