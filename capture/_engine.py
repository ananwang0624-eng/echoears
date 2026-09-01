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


class _RFFrames:
    """RangeSource beats reshaped into LiveSource-style frames.

    tools/record.capture() wants poll() -> [(ts, mag)] with mag stacked
    (n_channels, n_samples), plus channels/rx_ids/fop_hz/odr_ms. The
    rangefinder source instead emits one event per sensor per beat, so this
    pairs them up — same assembly the bridge does for its live frames.
    """

    def __init__(self, src):
        import numpy as np
        self._np = np
        self.src = src
        self.ids = list(src.ids)
        self.channels = [(s, s) for s in self.ids]     # pulse-echo only
        self.rx_ids = list(self.ids)
        self.fop_hz = [src.fop_hz.get(s, 176500.0) for s in self.ids]
        self.odr_ms = src.odr_ms
        self._pend: dict = {}

    def poll(self):
        out = []
        for ev in self.src.poll():
            self._pend[ev["sid"]] = ev
            if len(self._pend) == len(self.ids):
                mag = self._np.stack(
                    [self._np.abs(self._pend[s]["iq"]) for s in self.ids])
                out.append((int(self._pend[self.ids[0]]["ts"]), mag))
                self._pend = {}
        return out


def record_shot(label: str, seconds: float, note: str,
                rf_cfg: str | None = None) -> int:
    """Record one shot. Default source is the txrot LiveSource; pass
    `rf_cfg` ("short"/"long"/...) to record through the vendor rangefinder
    firmware instead — the same firmware+preset run/10 uses. That flashes
    gpt over txrot (run/8 flashes it back automatically) and needs no
    queue guard: the preset carries its own measurement sequence."""
    ensure_py39()
    banner(f"Capture · {label} ({seconds:.0f} s)", "Ctrl-C cancels (nothing written)")
    if rf_cfg is None:
        _queue_guard()
    else:
        print("  ⚠️  vendor rangefinder firmware — txrot gets evicted;")
        print("     running run/8_web.py afterwards flashes it back.\n")

    # resolve BEFORE the EVK stack loads: its bootstrap chdir()s
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{label}_{time.strftime('%Y%m%d_%H%M%S')}.npz"

    from tools.record import capture

    print(f"  Actions: {note}\n")
    print("[capture] bring-up (flash+calibration ~20 s) ...")
    if rf_cfg is None:
        from echoears.sources import LiveSource
        src_cm, odr = LiveSource(), 4
    else:
        from echoears.rangefinder import RangeSource
        src_cm, odr = RangeSource(cfg=rf_cfg), None
    with src_cm as raw:
        if rf_cfg is None:
            while not raw.channels:
                if not raw.poll():
                    time.sleep(0.02)
            src = raw
        else:
            raw.wait_for_data()
            src = _RFFrames(raw)
            odr = raw.cic_odr
        print(f"[capture] ready: {len(src.channels)} channels")
        input("  Get in position, then Enter to record: ")
        for n in (3, 2, 1):
            print(f"  {n} ...")
            time.sleep(1.0)
        print("  ● recording")
        entry = capture(src, seconds, label, note, out)
        if rf_cfg is not None:
            entry["rf_cfg"] = rf_cfg
            entry["cic_odr"] = odr

    mf = OUT_DIR / "manifest.json"
    entries = json.loads(mf.read_text()) if mf.exists() else []
    entries.append(entry)
    mf.write_text(json.dumps(entries, ensure_ascii=False, indent=2))

    py = sys.executable
    print(f"\n[capture] saved -> {out}")
    print(f"[capture] manifest {mf} ({len(entries)} entries)\n")
    print("Next steps (optional):")
    print(f"  # listen back\n  {py} {REPO}/apps/live.py --replay {out} --odr {odr}")
    print(f"  # export into the web demo\n  {py} {REPO}/tools/export_web.py {out} "
          f"--odr {odr} -o {REPO}/web/data/{out.stem} --title {label}")
    if rf_cfg is not None:
        print("  # note: recorded under the rangefinder preset — keep the "
              f"--odr {odr} above, NOT the txrot 4")
    return 0
