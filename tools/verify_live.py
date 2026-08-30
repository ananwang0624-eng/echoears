#!/usr/bin/env python3
"""Re-derive the hardware numbers in HANDOFF.md, or refute them.

    python tools/verify_live.py --seconds 35 --save out/verify.npz

Exists because a claim nobody can re-run is not evidence. Prints the same statistics for the live
rig and for any recording, so the two are comparable — and so is the honest
finding that most of them reproduce from a FILE, i.e. they say little about
hardware specifically.

    python tools/verify_live.py --replay out/scene233.npz --odr 4

What each number can and cannot show:
  cold-start p95   the warm-up blast the DSP review found. Seed-sensitive:
                   one cold start samples one seed, so --repeat matters.
  flatness         near-tautological on a static scene — to_sigma divides
                   each bin by its own spread, so p95 lands near 1.8 sigma
                   whatever you feed it. Reported for completeness only.
  false alarms     comparable ONLY against the same estimator: the streaming
                   RunningBaseline and the offline to_sigma differ by about
                   0.03 percentage points on the same data.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echoears import profile as prof  # noqa: E402

BANDS = [(20, 40), (40, 80), (80, 140), (140, 250)]


def stats(sig: np.ndarray, ax: np.ndarray, ts: np.ndarray, gate: float,
          full: float, label: str) -> None:
    print(f"\n=== {label} ===")
    print(f"{len(sig)} frames, {ts[-1]-ts[0]:.1f} s")
    print("cold start (the +16 dB warm-up blast, if any):")
    for lo, hi in [(0, 1), (1, 3), (3, 10), (10, 1e9)]:
        w = sig[(ts >= lo) & (ts < hi)]
        if not len(w):
            continue
        name = f"{lo}-{hi:g} s" if hi < 1e9 else f"{lo}+ s"
        print(f"  {name:<9} p95 {np.percentile(w,95):5.2f}s  max {w.max():6.2f}s"
              f"  >{full:.0f}s {100*(w>full).mean():7.4f}%")

    if sig.ndim != 3:                     # both paths give (frames, ch, bins)
        sig = sig[:, None, :]
    pe = list(range(sig.shape[1]))
    print("flatness per channel (near-tautological — see the docstring):")
    for c in pe:
        v = [np.percentile(sig[:, c, (ax >= lo) & (ax < hi)], 95)
             for lo, hi in BANDS if ((ax >= lo) & (ax < hi)).any()]
        print(f"  ch{c}: {' '.join(f'{x:.2f}' for x in v)}"
              f"   spread {20*np.log10(max(v)/min(v)):.2f} dB")
    # STEADY STATE only: a whole-run average includes the forced-zero seed
    # and the whole warm-up, which read 2.1x optimistic on the shorter file
    hz = len(sig) / max(ts[-1], 1e-9)
    settled = sig[ts >= (1.0 / 0.005) / hz]
    if len(settled):
        print(f"false alarms at {gate} sigma (streaming, settled frames only): "
              f"{100*(settled>gate).mean():.3f}%   "
              f"[whole run incl. warm-up: {100*(sig>gate).mean():.3f}%]")
    else:
        print(f"false alarms: run too short to contain settled frames "
              f"({len(sig)} frames; need > {1/0.005:.0f})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", type=Path, help="a recording instead of the rig")
    ap.add_argument("--odr", type=int, default=4)
    ap.add_argument("--seconds", type=float, default=35.0)
    ap.add_argument("--repeat", type=int, default=1,
                    help="cold starts to sample; the warm-up is seed-sensitive "
                         "and one run proves little. On --replay each repeat "
                         "starts at a different offset, so each is a genuinely "
                         "different seed rather than the same one re-run")
    ap.add_argument("--gate", type=float, default=3.5)
    ap.add_argument("--full-scale", type=float, default=8.0)
    ap.add_argument("--save", type=Path, help="keep the capture so the numbers "
                                              "stay falsifiable")
    args = ap.parse_args()
    smclk = prof.smclk_for_odr(args.odr)

    cold = []
    for run in range(1, args.repeat + 1):
        base = prof.RunningBaseline(alpha=0.02, sigma=True)
        rows, stamps = [], []
        if args.replay:
            from echoears.session import load
            sess = load(args.replay)
            span = prof.SCALE_SEED_FRAMES + int(args.seconds * (sess.frame_hz or 19.2))
            if args.repeat > 1 and args.repeat > sess.n_frames / max(span, 1):
                print(f"  ! {args.repeat} repeats over {sess.n_frames} frames "
                      f"means the runs overlap: they are rotations of ONE "
                      f"clutter realisation, not {args.repeat} samples of a "
                      f"population. Treat the spread as correlated.")
            ax = prof.range_axis(sess, 0, smclk_per_sample=smclk,
                                 tx_smclk=int(sess.meta.get("tx_smclk", 0)))
            hz = sess.frame_hz or 19.2
            frames = np.abs(sess.iq)
            # a different offset per repeat = a different seed, which is the
            # whole point; re-running from frame 0 would sample one seed N times
            off = ((run - 1) * len(frames) // max(args.repeat, 1)) % len(frames)
            # stop at the end rather than wrapping: the end->start step is
            # ~1.5x a normal frame-to-frame step and spikes the false-alarm
            # rate around it (0.545% vs 0.120% measured), so a wrapped run is
            # not comparable to the one unwrapped run
            for i in range(len(frames) - off):
                rows.append(base(frames[off + i]).copy())
                stamps.append(i / hz)
                if stamps[-1] > args.seconds:
                    break
            label = f"replay {args.replay.name} (run {run})"
        else:
            from echoears.sources import LiveSource, close_cleanly_on_sigterm
            close_cleanly_on_sigterm()
            with LiveSource() as src:
                while not src.channels:
                    if not src.poll():
                        time.sleep(0.02)
                ax = src.range_axis(0, smclk_per_sample=smclk)
                t0 = time.time()
                while time.time() - t0 < args.seconds:
                    for _ts, mag in src.poll():
                        rows.append(base(mag).copy())
                        stamps.append(time.time() - t0)
                    time.sleep(0.005)
            label = f"live rig (run {run})"

        sig = np.stack(rows)
        ts = np.asarray(stamps)
        # measure the first second AFTER the deliberate seed silence —
        # inside it the answer is trivially zero and proves nothing
        warm = prof.SCALE_SEED_FRAMES / max(len(sig) / max(ts[-1], 1e-9), 1e-9)
        first = sig[(ts >= warm) & (ts < warm + 1.0)]
        cold.append((np.percentile(first, 95), first.max(),
                     100 * (first > args.full_scale).mean()))
        if args.repeat <= 3:
            stats(sig, np.asarray(ax), ts, args.gate, args.full_scale, label)
        if args.save:
            dst = (args.save if args.repeat == 1
                   else args.save.with_name(f"{args.save.stem}_{run}"
                                            f"{args.save.suffix}"))
            np.savez_compressed(dst, sigma=sig, ts=np.asarray(stamps),
                                axis=np.asarray(ax))
            print(f"  saved -> {dst}")

    if args.repeat > 1:
        c = np.array(cold)
        print(f"\n=== cold start across {args.repeat} seeds "
              f"(first second after the {prof.SCALE_SEED_FRAMES}-frame seed) ===")
        print(f"  p95   min {c[:,0].min():.2f}  median {np.median(c[:,0]):.2f}"
              f"  max {c[:,0].max():.2f} sigma")
        print(f"  max   min {c[:,1].min():.2f}  median {np.median(c[:,1]):.2f}"
              f"  max {c[:,1].max():.2f} sigma")
        print(f"  over full scale: worst {c[:,2].max():.4f}%  "
              f"({int((c[:,2] > 0).sum())}/{args.repeat} runs non-zero)")
        print("  Compare against STEADY STATE, not against zero: bins above"
              "\n  full scale are the top of the range being used, and the "
              "settled\n  stream has them too (~0.001%). The pathology this "
              "watches for is\n  the original warm-up bug — 11.8% of bins over"
              " full scale for 20 s.\n  A real failure looks like percent, not"
              " thousandths of a percent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
