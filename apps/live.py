#!/usr/bin/env python3
"""Live binaural echo listening — glasses-temple sensors to headphones.

    # real hardware (board flashed + calibrated automatically, ~40 s startup):
    .venv-py39/bin/python apps/live.py --seconds 30

    # no hardware — same audio path driven from a recording:
    python apps/live.py --replay session.npz --odr 6

Left temple sensor -> left ear, right temple -> right ear. Two sensors
(ids 2 and 3), four channels, 233 cm at 20 Hz. The ears are the two pulse-echo
channels; override with --left/--right if the flex cabling is mirrored.

Each frame's range profile becomes one grain: near echoes early + high-pitched,
far echoes late + low. Static clutter (ringdown, frame) is removed with a
running baseline so silence really is silence.

Keep this process lean while the board streams: the serial reader thread
starves if the host hogs CPU (documented upstream as the board-wedging mode).
Audio synthesis here is ~1 ms per frame — fine.
"""

from __future__ import annotations

import argparse
import queue
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echoears import profile as prof  # noqa: E402
from echoears import sonify as son  # noqa: E402
from echoears.sources import (LiveSource, ReplaySource,  # noqa: E402
                              close_cleanly_on_sigterm, pick_stereo_pe)

SR = 44100


class StereoOut:
    """Queue-fed sounddevice stream; falls back to WAV-only when absent."""

    def __init__(self, enable_audio: bool):
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=8)
        self.dump: list[np.ndarray] = []
        self.stream = None
        if enable_audio:
            try:
                import sounddevice as sd
            except ImportError:
                print("[live] sounddevice not installed — writing WAV only")
            else:
                self.stream = sd.OutputStream(
                    samplerate=SR, channels=2, dtype="float32",
                    callback=self._callback, blocksize=0,
                )
                self.stream.start()
        self._leftover = np.zeros((0, 2), dtype=np.float32)

    def _callback(self, out, frames, _time, _status):
        buf = self._leftover
        while len(buf) < frames:
            try:
                buf = np.concatenate([buf, self.q.get_nowait()])
            except queue.Empty:
                break
        if len(buf) >= frames:
            out[:] = buf[:frames]
            self._leftover = buf[frames:]
        else:  # underrun: pad with silence rather than glitch
            out[:len(buf)] = buf
            out[len(buf):] = 0.0
            self._leftover = np.zeros((0, 2), dtype=np.float32)

    def push(self, stereo: np.ndarray):
        self.dump.append(stereo)
        if self.stream is not None:
            try:
                self.q.put_nowait(stereo)
            except queue.Full:
                pass  # never block: dropping audio beats starving the serial thread

    def close(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()


def run(source, ch_l: int, ch_r: int, args, frame_hz: float) -> np.ndarray:
    grain = max(1, int(round(SR / frame_hz)))
    # Same units as the web app: per-bin noise sigmas, so `--gate` means the
    # same thing here as the browser's gate slider and neither path needs a
    # decaying auto-gain to survive the 70 dB spread across the range axis.
    synth = dict(sr=SR, f_near=args.f_near, f_far=args.f_far, gamma=args.gamma)
    if args.sigma:
        synth.update(full_scale=args.full_scale, gate=args.gate)
    synth_l = son.GrainSynth(**synth)
    synth_r = son.GrainSynth(**synth)
    base = prof.RunningBaseline(alpha=args.alpha, sigma=args.sigma)
    out = StereoOut(enable_audio=not args.no_audio)

    print(f"[live] L=ch{ch_l} R=ch{ch_r}  {frame_hz:.1f} Hz  grain {grain} samp "
          f"({1000*grain/SR:.0f} ms)  Ctrl-C to stop")
    n = 0
    t0 = time.time()
    try:
        if isinstance(source, ReplaySource):
            period = 1.0 / frame_hz
            for _ts, mag in source.frames():
                res = base(mag)
                stereo = np.stack(
                    [synth_l.render(res[ch_l], grain),
                     synth_r.render(res[ch_r], grain)], axis=1) * args.gain
                out.push(stereo)
                n += 1
                time.sleep(period)          # real-time pacing
                if args.seconds and time.time() - t0 >= args.seconds:
                    break
        else:
            while not args.seconds or time.time() - t0 < args.seconds:
                got = source.poll()
                for _ts, mag in got:
                    res = base(mag)
                    stereo = np.stack(
                        [synth_l.render(res[ch_l], grain),
                         synth_r.render(res[ch_r], grain)], axis=1) * args.gain
                    out.push(stereo)
                    n += 1
                if n and n % 100 < len(got):
                    lm, rm = float(res[ch_l].max()), float(res[ch_r].max())
                    print(f"  {n} frames  {n/(time.time()-t0):5.1f} fps   "
                          f"L peak {lm:7.0f}   R peak {rm:7.0f}")
                time.sleep(0.005)
    except KeyboardInterrupt:
        print("\n[live] stopped by user")
    finally:
        out.close()

    print(f"[live] {n} frames in {time.time()-t0:.1f} s")
    return (np.concatenate(out.dump) if out.dump
            else np.zeros((0, 2), dtype=np.float32))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("source")
    src.add_argument("--replay", type=Path, help="drive from a recorded npz instead of hardware")
    src.add_argument("--odr", type=int, default=4,
                     help="CIC ODR of the meas queue (live default 4 = 233 cm @ 0.78 cm/bin; archived recordings are 6)")
    src.add_argument("--config", default=LiveSource.DEFAULT_CONFIG,
                     help="capture config (default: the 2-sensor temple pair)")
    src.add_argument("--com-port", default=None, help="default: first /dev/cu.usbmodem*")
    src.add_argument("--odr-ms", type=int, default=None,
                     help="beat interval; the 233 cm queue needs 25 ms "
                          "(24.0 ms of RX window + readout)")
    src.add_argument("--attempts", type=int, default=3,
                     help="retries when the board will not come up; each retry runs the recovery ladder")

    ears = ap.add_argument_group("ears")
    # id 3 = LEFT temple, id 2 = RIGHT — confirmed by ear 2026-08-28 (reversed sounds mirrored).
    ears.add_argument("--left-sensor", type=int, default=3, help="left-temple sensor id")
    ears.add_argument("--right-sensor", type=int, default=2, help="right-temple sensor id")
    ears.add_argument("--left", type=int, default=None, help="explicit L channel index")
    ears.add_argument("--right", type=int, default=None, help="explicit R channel index")

    au = ap.add_argument_group("audio")
    au.add_argument("--f-near", type=float, default=1800.0)
    au.add_argument("--f-far", type=float, default=300.0)
    au.add_argument("--gamma", type=float, default=0.5)
    au.add_argument("--gate", type=float, default=3.5,
                    help="silence below this many noise sigmas (web default 3.5)")
    au.add_argument("--full-scale", type=float, default=8.0,
                    help="sigmas that map to full volume (web FULL_SIGMA)")
    au.add_argument("--counts", dest="sigma", action="store_false", default=True,
                    help="pre-sigma behaviour: raw counts with the decaying "
                         "peak tracker, no gate. The defence-day escape hatch "
                         "if the sigma path ever sounds wrong on the night.")
    au.add_argument("--gain", type=float, default=0.6)
    au.add_argument("--alpha", type=float, default=0.02, help="baseline EMA rate")
    au.add_argument("--no-audio", action="store_true", help="skip sounddevice, WAV only")

    ap.add_argument("--seconds", type=float, default=None, help="stop after N seconds")
    ap.add_argument("--wav", type=Path, default=None, help="also write the session to WAV")
    args = ap.parse_args()
    close_cleanly_on_sigterm()
    # The EVK bootstrap os.chdir()s into its install dir on import, so resolve
    # every user path BEFORE the hardware stack loads.
    if args.wav:
        args.wav = args.wav.resolve()
        args.wav.parent.mkdir(parents=True, exist_ok=True)
    if args.replay:
        args.replay = args.replay.resolve()

    if args.replay:
        source = ReplaySource(args.replay, smclk_per_sample=prof.smclk_for_odr(args.odr))
        channels = source.channels
        frame_hz = source.frame_hz or 25.6
    else:
        source = LiveSource(args.config, args.com_port,
                            attempts=args.attempts, odr_ms=args.odr_ms)
        try:
            source.start()
        except RuntimeError as e:
            # Calibration failures are a hardware state, not a crash. The
            # upstream diagnosis (LINK-DEAD vs TX-MUTED) is already printed
            # above; add the remedy and exit quietly.
            print(f"\n  ❌ board failed to come up: {e}")
            print("     auto-recovery already ran — replug the USB cable, wait two seconds.")
            print("     still failing: check the flex cable seating.")
            return 2
        # From here the rig is STREAMING, so everything below must be inside
        # the try/finally — this spin loop is unbounded (a board that never
        # assembles a frame sits here forever) and used to hold the board
        # with no cleanup path at all.
        try:
            while not source.channels:  # need one assembled frame for geometry
                if not source.poll():
                    time.sleep(0.02)
        except BaseException:
            source.close()
            raise
        channels = source.channels
        frame_hz = source.frame_hz

    if args.left is not None and args.right is not None:
        ch_l, ch_r = args.left, args.right
    else:
        ch_l, ch_r = pick_stereo_pe(channels, args.left_sensor, args.right_sensor)

    try:
        audio = run(source, ch_l, ch_r, args, frame_hz)
    except KeyboardInterrupt:
        print("\n[live] stopped")
        audio = np.zeros((0, 2), dtype=np.float32)
    finally:
        if isinstance(source, LiveSource):
            source.close()

    if args.wav and len(audio):
        # absolute scale: see apps/play.py and sonify.write_wav
        son.write_wav(args.wav, audio, peak=None if args.sigma else 0.89)
        print(f"[live] wrote {args.wav} ({len(audio)/SR:.1f} s stereo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
