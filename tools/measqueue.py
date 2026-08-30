#!/usr/bin/env python3
"""Plan and write a longer-range meas queue for the txrot firmware.

    # what would 120 cm cost? (no files touched)
    python tools/measqueue.py plan --range-cm 120

    # write a new queue next to the original
    python tools/measqueue.py write --range-cm 120 --odr 4 \
        -o ~/Documents/GitHub/ultrasonic/firmware/txrot/txrot_long120.json

    # read back any queue and print what it actually does
    python tools/measqueue.py show <queue.json>

WHAT SETS WHAT
    range      <- total RX instruction length (SMCLK). This is the only knob
                  that buys reach; it is how long the sensor listens.
    samples     = rx_smclk / smclk_per_sample
    resolution <- CIC ODR (smclk_per_sample = 16 * 2**(7-odr))

ODR does not extend range. Setting it alone keeps the same listening window
and just samples it more coarsely -- the vendor's rx_length drops from 115 to
29 when you go odr 6 -> 4. ODR matters because the IQ buffer holds at most 340
samples, so a fine ODR runs out of buffer before it runs out of listening time.

Edits go through the vendor's own CfgWriter, never by hand-patching the
bit-packed cmd_config fields.

Must run under the EVK py3.9 interpreter:
    ~/Documents/GitHub/ultrasonic/.venv-py39/bin/python
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ULTRASONIC = Path.home() / "Documents" / "GitHub" / "ultrasonic"
DEFAULT_QUEUE = ULTRASONIC / "firmware" / "txrot" / "txrot_defaults.json"

sys.path.insert(0, str(REPO))
from echoears.profile import (  # noqa: E402
    IQ_SAMPLES_MAX, ODR_SMCLK_PER_SAMPLE, max_range_cm, rx_smclk_for_range,
    smclk_for_odr,
)

FOP_HZ = 176_500.0  # measured typical across the three sensors


def _load_cfgwriter(path: Path):
    """Import the vendor stack lazily; it chdir()s and is py3.9-only."""
    sys.path.insert(0, str(ULTRASONIC))
    from common.evk import bootstrap  # noqa: F401  (side effects: paths, patches)
    from invn.pysonic.cfgwriter import CfgWriter

    return CfgWriter(str(path))


# ---------------------------------------------------------------- plan ----
def cmd_plan(args) -> int:
    target = args.range_cm
    print(f"target {target:.0f} cm pulse-echo object range, fop {FOP_HZ/1000:.1f} kHz\n")

    smclk_needed = rx_smclk_for_range(target, FOP_HZ, pulse_echo=True)
    seconds = smclk_needed / (16.0 * FOP_HZ)
    print(f"RX listening window needed: {smclk_needed:,} SMCLK  ({seconds*1000:.2f} ms)")
    print(f"  (current queue listens 3,664 SMCLK = 1.31 ms = 22.4 cm)\n")

    # THREE ceilings, not one:
    #   1. the IQ buffer caps a measurement at IQ_SAMPLES_MAX samples
    #   2. the RX listening window itself has to fit inside one beat period --
    #      it is real time spent listening, n * smclk / (16*fop) seconds
    #   3. the bridge<->sensor SPI readout has to fit in what is left
    # (2) is the one that actually binds at long range and the one this tool
    # used to ignore, which is how it recommended a 340-sample queue whose
    # 15.4 ms window cannot fit a 13 ms beat.
    print(f"{'ODR':>4} {'SMCLK/sa':>9} {'samples':>8} {'buf':>5} "
          f"{'PE step':>9} {'PE reach':>9} {'RXwin':>8} {'readout':>8} "
          f"{'beat':>7} {'odr_ms':>7} {'fps':>6}")
    rows = []
    for odr in sorted(ODR_SMCLK_PER_SAMPLE, reverse=True):
        smclk = smclk_for_odr(odr)
        n = int(round(smclk_needed / smclk))
        fits_buf = n <= IQ_SAMPLES_MAX
        pe = max_range_cm(n, FOP_HZ, smclk_per_sample=smclk, pulse_echo=True)
        step = pe / n if n else 0
        rx_ms = n * smclk / (16.0 * FOP_HZ) * 1000.0
        tx_ms = args.tx / FOP_HZ * 1000.0             # burst is real beat time
        readout_ms = 2.0 * n / 115.0 * args.n_tx      # all sensors in one beat
        beat_ms = tx_ms + rx_ms + readout_ms
        odr_floor = max(args.odr_ms, int(beat_ms) + 1)
        fps = 1000.0 / (args.n_tx * odr_floor)
        rows.append((odr, n, fits_buf, odr_floor, fps))
        print(f"{odr:>4} {smclk:>9} {n:>8} {'ok' if fits_buf else 'NO':>5} "
              f"{step:>8.3f}c {pe:>8.1f}c {rx_ms:>7.1f}m {readout_ms:>7.1f}m "
              f"{beat_ms:>6.1f}m {odr_floor:>7} {fps:>6.1f}")

    # Prefer the finest ODR that fits the buffer AND keeps the current beat
    # interval, i.e. costs no frame rate. Fall back to buffer-only if none.
    keeps_rate = [r for r in rows if r[2] and r[3] <= args.odr_ms]
    fits_only = [r for r in rows if r[2]]
    best = keeps_rate[0] if keeps_rate else (fits_only[0] if fits_only else None)

    if best is None:
        print(f"\nno ODR fits {target:.0f} cm in {IQ_SAMPLES_MAX} samples "
              f"-- reduce the range.")
        return 0

    odr, n, _, floor, fps = best
    if keeps_rate:
        print(f"\nrecommended: ODR={odr}, n_samples={n}")
        print(f"  finest resolution that fits the {IQ_SAMPLES_MAX}-sample buffer "
              f"AND keeps odr_ms={args.odr_ms} ({fps:.1f} Hz).")
        finer = [r for r in rows if r[2] and r[0] > odr]
        if finer:
            f0 = finer[-1]
            print(f"  ODR={f0[0]} would be finer but needs odr_ms>={f0[3]} "
                  f"-> {f0[4]:.1f} Hz instead of {fps:.1f} Hz.")
    else:
        print(f"\nbuffer-limited pick: ODR={odr}, n_samples={n} — but readout "
              f"forces odr_ms>={floor} ({fps:.1f} Hz, down from "
              f"{1000/(args.n_tx*args.odr_ms):.1f} Hz).")

    print(f"  write it with:  python tools/measqueue.py write "
          f"--range-cm {target:.0f} --odr {odr}")
    print("\n  RXwin is exact (n * SMCLK / clock). readout is an estimate scaled "
          "from\n  upstream's 2 ms @115 samples. beat = RXwin + readout must fit "
          "odr_ms.\n  Verify the frame rate on hardware before trusting it.")
    return 0


# ---------------------------------------------------------------- show ----
def cmd_show(args) -> int:
    path = Path(args.queue).expanduser().resolve()
    cw = _load_cfgwriter(path)
    print(f"{path}\n")
    for i, mq in enumerate(cw.meas_queues):
        odr = mq.cic_odr
        n = mq.rx_length
        smclk = smclk_for_odr(odr)
        pe = max_range_cm(n, FOP_HZ, smclk_per_sample=smclk, pulse_echo=True)
        pc = max_range_cm(n, FOP_HZ, smclk_per_sample=smclk, pulse_echo=False)
        used = sum(1 for t in mq.trx_insts if getattr(t, "length", 0))
        # Some params live in meas_cfg rather than meas and raise KeyError.
        try:
            rd = mq.ringdown_cancel_samples
        except (KeyError, AttributeError):
            rd = "n/a"
        print(f"meas[{i}]  odr={odr}  rx_length={n}  tx_length={mq.tx_length}")
        print(f"          window {n*smclk:,} SMCLK = {n*smclk/(16*FOP_HZ)*1000:.2f} ms")
        print(f"          PE {pe:.1f} cm   PC {pc:.1f} cm   step {pe/n:.3f} cm")
        print(f"          ringdown_cancel={rd}  instructions used {used}/32")
    return 0


# --------------------------------------------------------------- write ----
def cmd_write(args) -> int:
    src = Path(args.source).expanduser().resolve()
    dst = Path(args.out).expanduser().resolve()
    smclk = smclk_for_odr(args.odr)
    smclk_needed = rx_smclk_for_range(args.range_cm, FOP_HZ, pulse_echo=True)
    n = int(round(smclk_needed / smclk))

    if n > IQ_SAMPLES_MAX:
        print(f"refusing: {args.range_cm:.0f} cm at ODR={args.odr} needs {n} "
              f"samples, buffer holds {IQ_SAMPLES_MAX}. Use a coarser ODR.")
        return 2

    cw = _load_cfgwriter(src)
    before = [(mq.cic_odr, mq.rx_length, mq.tx_length) for mq in cw.meas_queues]

    for mq in cw.meas_queues:
        mq.cic_odr = args.odr        # ORDER MATTERS: odr first...
        mq.rx_length = n             # ...then the window, which rewrites RX insts
        if args.tx is not None:
            # TX burst length in PMUT cycles (length field = cycles*16 SMCLK).
            # TX does NOT set the range axis — ODR and the RX window do. It
            # sets the energy in the air, i.e. whether the far end of that
            # window contains anything above the noise. The vendor pairs
            # them: medfilt/icu-10201 presets run TX 16/32/48/160 cycles
            # under 19/78/157/314 cm windows. Datasheet ceiling regardless:
            # 1.7 m wall, 1.1 m post (ds-000480) — a longer window than that
            # is listening room, not detection range.
            #
            # tx_length is a derived read-only sum; the write path is the
            # instruction itself. In-place .length keeps every other bit
            # (phase 8 / pulse_width 4 — already identical to the vendor's
            # own Long Range TX, cmd_config 33825). uint16 in firmware.
            if not 1 <= args.tx <= 4095:
                print(f"refusing: tx {args.tx} cycles outside 1..4095 "
                      f"(uint16 SMCLK field)")
                return 2
            tx_inst = next((i for i in mq.trx_insts if i.is_tx_inst()), None)
            if tx_inst is None:
                print("refusing: source queue has no TX instruction to modify")
                return 2
            tx_inst.length = args.tx * 16

    after = [(mq.cic_odr, mq.rx_length, mq.tx_length) for mq in cw.meas_queues]
    for i, ((o0, n0, t0), (o1, n1, t1)) in enumerate(zip(before, after)):
        pe = max_range_cm(n1, FOP_HZ, smclk_per_sample=smclk_for_odr(o1))
        print(f"meas[{i}]  odr {o0}->{o1}   rx_length {n0}->{n1}   "
              f"tx_length {t0}->{t1}   PE reach {pe:.1f} cm")
        if n1 != n:
            print(f"          NOTE: vendor rounded {n} -> {n1}")
        if t1 and t1 >= 64:
            burst_cm = 34300.0 * (t1 / FOP_HZ) / 2
            print(f"          NOTE: {t1}-cycle burst is ~{burst_cm:.0f} cm long in "
                  f"air — that, not the bin size, is the resolution now, and "
                  f"ringdown will eat more of the near field.")

    if dst.exists() and not args.force:
        print(f"\n{dst} exists; pass --force to overwrite.")
        return 2
    if dst.resolve() == src.resolve():
        backup = src.with_suffix(".json.bak")
        shutil.copy2(src, backup)
        print(f"\nbacked up original -> {backup}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    cw.write(str(dst))
    print(f"wrote {dst}")

    print(f"""
NEXT — three things must move together or the range axis lies silently:

  1. point the plugin at it. In
       {ULTRASONIC}/.venv-py39/evk_pkgs/invn/pysonic/PysonicPlugins.toml
     under [plugins.txrot], set BOTH
       json_defaults                  = "{dst}"
       per_sensor_defaults."icu-10201" = "{dst}"
     (the per-sensor entry overrides the global one)

  2. tell echoears the new resolution: pass --odr {args.odr} to apps/*.py

  3. if you record with the upstream matrix track, it hardcodes
     SMCLK_PER_SAMPLE = 32 in matrix/frames.py -- change it to {smclk}
     and add a new CaptureConfig with n_samples={n}, or every stored cm
     band is mislabeled with no error.

Re-running tools/setup_mac_py39.py overwrites the venv toml; re-apply step 1.""")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="cost out a target range, touch nothing")
    p.add_argument("--range-cm", type=float, default=120.0)
    p.add_argument("--tx", type=int, default=160,
                   help="TX burst cycles assumed in the beat budget")
    p.add_argument("--odr-ms", type=int, default=26, help="current beat interval")
    p.add_argument("--n-tx", type=int, default=2,
                   help="sensors in the rotation (temple pair = 2)")
    p.set_defaults(func=cmd_plan)

    s = sub.add_parser("show", help="decode an existing queue")
    s.add_argument("queue", nargs="?", default=str(DEFAULT_QUEUE))
    s.set_defaults(func=cmd_show)

    w = sub.add_parser("write", help="write a modified queue")
    w.add_argument("--range-cm", type=float, required=True)
    w.add_argument("--odr", type=int, required=True)
    w.add_argument("--tx", type=int, default=None,
                   help="TX burst length in fop cycles (vendor: 16 short, "
                        "32 default, 160 long range); default keeps source")
    w.add_argument("--source", default=str(DEFAULT_QUEUE))
    w.add_argument("-o", "--out", required=True)
    w.add_argument("--force", action="store_true")
    w.set_defaults(func=cmd_write)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
