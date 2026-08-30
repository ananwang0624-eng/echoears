#!/usr/bin/env python3
"""Print what is actually in a recorded session, including an ASCII profile.

    python apps/show.py path/to/session.npz --odr 6

Proves the reader and the range axis work before any audio is involved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echoears import profile as prof  # noqa: E402
from echoears.session import load  # noqa: E402

BLOCKS = " .:-=+*#%@"


def sparkline(values: np.ndarray, width: int = 64) -> str:
    """Log-scaled ASCII bar of a range profile."""
    v = np.interp(np.linspace(0, len(values) - 1, width),
                  np.arange(len(values)), values)
    v = np.log10(v + 1.0)
    hi = v.max()
    if hi <= 0:
        return " " * width
    idx = np.clip((v / hi * (len(BLOCKS) - 1)).astype(int), 0, len(BLOCKS) - 1)
    return "".join(BLOCKS[i] for i in idx)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("npz", type=Path)
    ap.add_argument("--odr", type=int, required=True,
                    help="CIC ODR the file was captured at (6 for the current "
                         "txrot_defaults.json). Required: it is NOT stored in the npz.")
    ap.add_argument("--static", action="store_true",
                    help="also show the profile with static clutter removed")
    args = ap.parse_args()

    smclk = prof.smclk_for_odr(args.odr)
    sess = load(args.npz)

    print(sess.describe())
    print(f"\nCIC ODR {args.odr} -> {smclk} SMCLK/sample (supplied, not stored in file)")

    print("\nper-channel range coverage")
    print(f"  {'ch':>3} {'tx>rx':>6} {'kind':>3} {'step cm':>8} {'max cm':>8}")
    for ch in range(sess.n_channels):
        tx, rx = (int(v) for v in sess.channels[ch])
        ax = prof.range_axis(sess, ch, smclk_per_sample=smclk)
        kind = "PE" if tx == rx else "PC"
        print(f"  {ch:>3} {f'{tx}>{rx}':>6} {kind:>3} {ax[0]:>8.3f} {ax[-1]:>8.1f}")

    print("\nmean |IQ| vs distance   (log scale, near -> far)")
    for ch in range(sess.n_channels):
        tx, rx = (int(v) for v in sess.channels[ch])
        ax = prof.range_axis(sess, ch, smclk_per_sample=smclk)
        mag = prof.magnitude(sess, ch)
        mean = mag.mean(axis=0)
        tag = "PE" if tx == rx else "PC"
        print(f"  ch{ch} {tx}>{rx} {tag} |{sparkline(mean)}| 0-{ax[-1]:.0f}cm  peak "
              f"{ax[int(np.argmax(mean))]:.1f}cm")

    if args.static:
        print("\nsame, static clutter removed (temporal median subtracted)")
        for ch in range(sess.n_channels):
            tx, rx = (int(v) for v in sess.channels[ch])
            ax = prof.range_axis(sess, ch, smclk_per_sample=smclk)
            moving = prof.remove_static(prof.magnitude(sess, ch))
            mean = moving.mean(axis=0)
            tag = "PE" if tx == rx else "PC"
            peak = ax[int(np.argmax(mean))] if mean.max() > 0 else float("nan")
            print(f"  ch{ch} {tx}>{rx} {tag} |{sparkline(mean)}| peak {peak:.1f}cm")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
