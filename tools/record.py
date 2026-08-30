#!/usr/bin/env python3
"""Record a live session to a schema-v1 npz that echoears/session.py loads.

    python tools/record.py --seconds 45 --label hand --note "hand moving" \
        -o out/hand233.npz

Magnitudes only: LiveSource yields |IQ|, so the stored iq is real-valued
cast to complex64 — np.abs() round-trips it, which is all any consumer
(sonify, export_web, replay) ever does.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echoears import profile as prof  # noqa: E402
from echoears.sources import LiveSource  # noqa: E402


def capture(src, seconds: float, label: str, note: str, out: Path) -> dict:
    """Record `seconds` from an ALREADY-OPEN source into a schema-v1 npz.

    Separate from bring-up so a shot list (tools/capture.py) records many
    files on ONE board programming — reflash cycles wear this board into
    OTP wedges. Drains the source's backlog first, so frames buffered while
    the operator read instructions don't leak into the take.

    Returns a manifest entry for the file it wrote.
    """
    out = Path(out).expanduser().resolve()
    src.poll()                                  # drop the backlog
    frames, stamps = [], []
    t0 = time.time()
    last = 0
    while time.time() - t0 < seconds:
        for ts, mag in src.poll():
            frames.append(mag.astype(np.float32))
            stamps.append(ts)
        time.sleep(0.005)
        sec = int(time.time() - t0)
        if sec != last and sec % 5 == 0:
            last = sec
            print(f"  {sec:.0f}s  {len(frames)} frames")
    if not frames:
        raise RuntimeError("0 frames — 板子没有在出流")

    iq = np.stack(frames).astype(np.complex64)          # (n, ch, s), imag=0
    ts_col = np.asarray(stamps, dtype=np.float64)[:, None]  # (n, 1)
    created = time.strftime("%Y-%m-%dT%H:%M:%S")

    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out, iq=iq, ts_us=ts_col,
        channels=np.asarray(src.channels),
        rx_ids=np.asarray(src.rx_ids),
        fop_hz=np.asarray(src.fop_hz, dtype=float),
        schema=np.array(1), label=np.array(label), note=np.array(note),
        created=np.array(created),
        # the axis facts a replayer needs; tx_smclk shifts the origin
        odr_ms=np.array(getattr(src, "odr_ms", LiveSource.DEFAULT_ODR_MS)),
        tx_smclk=np.array(prof.LIVE_TX_SMCLK),
    )
    hz = len(frames) / seconds
    print(f"[record] {len(frames)} frames ({hz:.1f} Hz) -> {out}")
    return {"file": str(out), "label": label, "note": note,
            "seconds": seconds, "frames": len(frames), "hz": round(hz, 2),
            "created": created}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--label", default="live")
    ap.add_argument("--note", default="")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    # resolve BEFORE the EVK stack loads: its bootstrap chdir()s, so a
    # relative -o would land in the EVK checkout, not where you asked.
    out = args.out.expanduser().resolve()

    with LiveSource() as src:
        while not src.channels:
            if not src.poll():
                time.sleep(0.02)
        print(f"[record] {args.seconds:.0f} s @ {src.frame_hz:.1f} Hz — 开始")
        capture(src, args.seconds, args.label, args.note, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
