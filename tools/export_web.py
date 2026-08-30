#!/usr/bin/env python3
"""Pack a recorded session into something a browser can fetch.

    python tools/export_web.py <session.npz> --odr 4 -o web/data/scene233

Writes two files:
    <name>.json   metadata: channels, range axis, frame rate, scaling
    <name>.bin    uint8, frame-major, (n_frames, n_ch, n_samples)

Values are in PER-BIN NOISE SIGMAS (see profile.to_sigma), not raw counts:
raw magnitudes span ~70 dB across the range axis, so no single threshold or
loudness curve can serve both the 20 cm ringdown and a 2 m wall. In sigma
units the static-scene level is flat to ~1 dB across the whole axis, so one
gate setting means the same thing everywhere — and the quantiser can be
linear, because the dynamic range problem was solved upstream rather than
papered over with a log curve.

Encoding: code = round(sigma / sigmaPerCode), clipped to 255. The exact same
decode runs in web/js/data.js; the round-trip is unit-tested.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echoears import detect, profile as prof  # noqa: E402
from echoears.session import load  # noqa: E402

#: Sigmas per uint8 code. 0.125 gives 0-31.9 sigma, which covers everything
#: a real echo reaches (a static scene tops out near 6) at a resolution far
#: finer than the ear or the eye can use.
SIGMA_PER_CODE = 0.125


def encode(sigma: np.ndarray) -> np.ndarray:
    """(n_frames, n_ch, n_samples) sigmas -> uint8.

    Linear, because to_sigma already flattened the 70 dB range problem that
    the old log curve existed to hide. Round, not truncate: astype() floors
    and would bias every code by half an LSB.
    """
    codes = np.clip(np.round(np.clip(sigma, 0, None) / SIGMA_PER_CODE), 0, 255)
    return codes.astype(np.uint8)


def ears_channels(channels, left_sensor: int, right_sensor: int):
    """[left PE ch, right PE ch], or None when either sensor has no PE channel.

    Same physical truth as tools/bridge.py: sensor 2 is the RIGHT temple.
    None (not a guess) for rigs that lack one of the sensors — the browser
    then falls back to its own ordering instead of silently mirroring L/R.
    """
    pe_of = {t: i for i, (t, r) in enumerate(channels) if t == r}
    if {left_sensor, right_sensor} <= set(pe_of):
        return [pe_of[left_sensor], pe_of[right_sensor]]
    return None


#: Full-scale ceiling of the sigma encoding. `peak` means THIS in both the
#: exporter and the bridge — the value code 255 stands for, not whatever the
#: data happened to reach.
SIGMA_CEILING = 255 * SIGMA_PER_CODE
#: mirrors FULL_SIGMA in web/js/data.js — where the browser actually saturates
WEB_FULL_SIGMA = 8.0


def _encode_raw(mag: np.ndarray) -> tuple[np.ndarray, float]:
    """--raw: log-compressed counts, the pre-sigma encoding, kept so the
    'this is what unprocessed data looks like' demo still works. Returns the
    codes and the peak needed to invert them."""
    peak = max(float(mag.max()) if mag.size else 1.0, 1.0)
    lg = np.log10(1.0 + np.clip(mag, 0, None))
    codes = np.clip(np.round(lg / np.log10(1.0 + peak) * 255.0),
                    0, 255).astype(np.uint8)
    return codes, peak


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("npz", type=Path)
    ap.add_argument("--odr", type=int, required=True,
                    help="CIC ODR at capture (not stored in the npz)")
    ap.add_argument("-o", "--out", type=Path, required=True,
                    help="output stem; .json and .bin are appended")
    ap.add_argument("--static", action="store_true", default=True,
                    help="remove static clutter (default on — ringdown otherwise "
                         "dominates every frame)")
    ap.add_argument("--raw", dest="static", action="store_false",
                    help="keep the clutter, for showing what raw data looks like")
    ap.add_argument("--frames", type=int, default=None, help="cap frame count")
    ap.add_argument("--title", default=None)
    # Which temple is which — same physical truth as tools/bridge.py.
    # Without this the browser falls back to ascending-sensor-id order and
    # mirrors L/R for the pair23 rig (sensor 2 is the RIGHT temple).
    ap.add_argument("--left-sensor", type=int, default=3)
    ap.add_argument("--right-sensor", type=int, default=2)
    args = ap.parse_args()

    smclk = prof.smclk_for_odr(args.odr)
    sess = load(args.npz)
    n_frames = min(args.frames or sess.n_frames, sess.n_frames)

    mag = np.abs(sess.iq[:n_frames]).astype(np.float64)   # (n, ch, s)
    if args.static:
        # per-bin noise normalisation: clutter removal AND the fix for the
        # 70 dB range spread, in one pass (profile.to_sigma explains why)
        sig = np.empty_like(mag)
        for c in range(mag.shape[1]):
            sig[:, c, :] = prof.to_sigma(mag[:, c, :])
        mag = sig
    else:
        # --raw keeps ADC counts; the browser is told so via `units`
        pass

    if args.static:
        codes, peak = encode(mag), SIGMA_CEILING
        # what matters is the browser's full scale, not the code ceiling:
        # data.js/audio.js saturate at FULL_SIGMA long before code 255
        clipped = float((mag > WEB_FULL_SIGMA).mean())
    else:
        codes, peak = _encode_raw(mag)
        clipped = 0.0

    dst = args.out.expanduser().resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    (dst.with_suffix(".bin")).write_bytes(codes.tobytes())

    # hardware-rule targets, per frame per channel: the vendor threshold
    # curve applied to RAW magnitudes (with median ringdown cancellation),
    # i.e. what the on-chip rangefinder would have reported. Computed here
    # because the shipped bins are sigma-quantised and the raw counts this
    # rule needs do not survive the export.
    raw = np.abs(sess.iq[:n_frames]).astype(np.float64)
    curve = detect.threshold_curve(raw.shape[2])
    txs = int(sess.meta.get("tx_smclk", 0))
    ests = [np.median(raw[:, c, :], axis=0) for c in range(raw.shape[1])]
    axes_t = [prof.range_axis(sess, c, smclk_per_sample=smclk, tx_smclk=txs)
              for c in range(raw.shape[1])]
    targets = [
        [[[round(float(axes_t[c][i]), 1), round(o, 2)]
          for i, o in detect.detect_targets(raw[f, c], curve,
                                            static_est=ests[c])]
         for c in range(raw.shape[1])]
        for f in range(raw.shape[0])
    ]

    channels = [[int(t), int(r)] for t, r in sess.channels]
    ears = ears_channels(channels, args.left_sensor, args.right_sensor)
    tx_smclk = int(sess.meta.get("tx_smclk", 0))
    meta = {
        "title": args.title or f"{sess.label} — {args.npz.name}",
        "label": sess.label,
        "source": args.npz.name,
        "odr": args.odr,
        "smclkPerSample": smclk,
        "nFrames": int(n_frames),
        "nChannels": int(mag.shape[1]),
        "nSamples": int(mag.shape[2]),
        "frameHz": round(sess.frame_hz, 3),
        "peak": peak,
        "units": "sigma" if args.static else "counts",
        "sigmaPerCode": SIGMA_PER_CODE if args.static else None,
        "sigmaCeiling": SIGMA_CEILING if args.static else None,
        "staticRemoved": bool(args.static),
        "channels": channels,
        "pulseEcho": [i for i, (t, r) in enumerate(channels) if t == r],
        "ears": ears,               # [left ch, right ch] or null (old rigs)
        # [frame][channel] -> up to 5 of [range_cm, over]; `over` is
        # magnitude / vendor threshold at that bin (>1 by construction)
        "targets": targets,
        "txSmclk": tx_smclk,
        # One range axis per channel — pulse-echo bins are half the pitch-catch
        # step, so a single shared axis would mislabel half the channels.
        "rangeCm": [
            [round(v, 4) for v in prof.range_axis(
                sess, c, smclk_per_sample=smclk, tx_smclk=tx_smclk)]
            for c in range(mag.shape[1])
        ],
        "note": sess.meta.get("note", ""),
        "created": sess.meta.get("created", ""),
    }
    (dst.with_suffix(".json")).write_text(json.dumps(meta, indent=1))

    kb = dst.with_suffix(".bin").stat().st_size / 1024
    print(f"{sess.label}: {n_frames} frames x {mag.shape[1]}ch x {mag.shape[2]}s")
    unit = "sigma" if args.static else "counts"
    print(f"  frame rate {sess.frame_hz:.2f} Hz   peak {mag.max():.1f} {unit}   "
          f"static removed {args.static}")
    if clipped:
        print(f"  {100*clipped:.5f}% of samples exceed the browser's "
              f"{WEB_FULL_SIGMA:.0f} sigma full scale")
    print(f"  range 0-{meta['rangeCm'][0][-1]:.1f} cm (ch0), "
          f"0-{meta['rangeCm'][1][-1]:.1f} cm (ch1)")
    print(f"  wrote {dst.with_suffix('.bin').name} ({kb:.0f} KB) "
          f"+ {dst.with_suffix('.json').name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
