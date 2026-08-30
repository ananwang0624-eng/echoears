#!/usr/bin/env python3
"""Sonify a recorded session to a WAV file.

    python apps/play.py session.npz --odr 6 -o out.wav
    python apps/play.py session.npz --odr 6 --stereo 6 2 --speed 0.25

Mono uses one channel; --stereo takes two channel indices and pans them hard
left / right, which is the cheapest possible spatial cue.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echoears import profile as prof  # noqa: E402
from echoears import sonify as son  # noqa: E402
from echoears.session import load  # noqa: E402


def channel_audio(sess, ch, *, smclk, static, frame_hz, args) -> np.ndarray:
    """`static` is now the default; --counts opts back into the old path."""
    mag = prof.magnitude(sess, ch)
    # sigma domain by default, so the WAV matches what the browser plays;
    # --raw keeps the old counts + per-file peak normalisation
    if static and not getattr(args, "raw", False):
        return son.sonify(
            prof.to_sigma(mag), frame_hz=frame_hz, speed=args.speed,
            f_near=args.f_near, f_far=args.f_far,
            sweep=not args.no_sweep, gamma=args.gamma,
            full_scale=args.full_scale, gate=args.gate,
        )
    if static:
        mag = prof.remove_static(mag)
    return son.sonify(
        mag, frame_hz=frame_hz, speed=args.speed,
        f_near=args.f_near, f_far=args.f_far,
        sweep=not args.no_sweep, gamma=args.gamma,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("npz", type=Path)
    ap.add_argument("--odr", type=int, required=True,
                    help="CIC ODR at capture (not stored in the npz)")
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--ch", type=int, default=0, help="channel for mono output")
    ap.add_argument("--stereo", nargs=2, type=int, metavar=("LEFT", "RIGHT"),
                    help="two channel indices panned hard L/R")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="1.0 = real time; 0.25 = 4x slower")
    ap.add_argument("--frames", type=int, default=None, help="use only the first N frames")
    ap.add_argument("--no-static", dest="static", action="store_false",
                    default=True,
                    help="keep static clutter (ringdown/rig); default removes it")
    ap.add_argument("--f-near", type=float, default=1800.0)
    ap.add_argument("--f-far", type=float, default=300.0)
    ap.add_argument("--no-sweep", action="store_true", help="fixed carrier pitch")
    ap.add_argument("--gamma", type=float, default=0.5)
    ap.add_argument("--gate", type=float, default=3.5,
                    help="silence below this many noise sigmas")
    ap.add_argument("--full-scale", type=float, default=8.0,
                    help="sigmas that map to full volume")
    ap.add_argument("--counts", dest="raw", action="store_true",
                    help="counts + per-file peak normalisation (pre-sigma "
                         "behaviour); the WAV then will not match the web app")
    args = ap.parse_args()

    smclk = prof.smclk_for_odr(args.odr)
    sess = load(args.npz)
    frame_hz = sess.frame_hz or 25.6

    if args.frames:
        sess.iq = sess.iq[: args.frames]
        sess.ts_us = sess.ts_us[: args.frames]

    if args.stereo:
        left, right = args.stereo
        chans = [left, right]
        a = channel_audio(sess, left, smclk=smclk, static=args.static,
                          frame_hz=frame_hz, args=args)
        b = channel_audio(sess, right, smclk=smclk, static=args.static,
                          frame_hz=frame_hz, args=args)
        audio = np.stack([a, b], axis=1)
    else:
        chans = [args.ch]
        audio = channel_audio(sess, args.ch, smclk=smclk, static=args.static,
                              frame_hz=frame_hz, args=args)

    out = args.out or args.npz.with_suffix(".wav").name
    # peak=None on the sigma path: renormalising per file would undo the
    # absolute scale and make a quiet recording as loud as a busy one
    son.write_wav(out, audio, peak=0.89 if args.raw or not args.static else None)

    ax = prof.range_axis(sess, chans[0], smclk_per_sample=smclk)
    dur = len(audio) / 44100
    print(f"{sess.label}  {sess.n_frames} frames @ {frame_hz:.1f} Hz")
    print(f"channels {chans}  range 0-{ax[-1]:.1f} cm  step {ax[0]:.3f} cm")
    print(f"speed {args.speed}x  static-removed {args.static}  "
          f"sweep {not args.no_sweep} ({args.f_near:.0f}->{args.f_far:.0f} Hz)")
    print(f"wrote {out}  ({dur:.1f} s, {'stereo' if args.stereo else 'mono'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
