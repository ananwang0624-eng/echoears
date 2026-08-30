"""Frame sources — where distance profiles come from.

    ReplaySource  recorded npz, no hardware
    LiveSource    EVK board via the sibling `ultrasonic` repo

Both yield the same thing: (ts_us, magnitude-frame) pairs. Everything
downstream (profiles, sonification, UI) is source-agnostic.
"""

from __future__ import annotations

import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Iterator

import numpy as np

from . import profile as prof
from .session import Session, load

ULTRASONIC_REPO = Path.home() / "Documents" / "GitHub" / "ultrasonic"


class ReplaySource:
    """Iterate the frames of a recorded session."""

    def __init__(self, path: str | Path, ch: int = 0, *, smclk_per_sample: int):
        self.session: Session = load(path)
        self.ch = ch
        self.smclk_per_sample = smclk_per_sample
        self.range_cm = prof.range_axis(self.session, ch, smclk_per_sample=smclk_per_sample)

    @property
    def frame_hz(self) -> float:
        return self.session.frame_hz

    @property
    def channels(self):
        return [tuple(int(v) for v in c) for c in self.session.channels]

    def magnitude(self) -> np.ndarray:
        """Whole session, one channel: (n_frames, n_samples)."""
        return prof.magnitude(self.session, self.ch)

    def __iter__(self) -> Iterator[tuple[int, np.ndarray]]:
        """(ts_us, (n_samples,)) for the configured single channel."""
        mag = self.magnitude()
        for i in range(self.session.n_frames):
            yield int(self.session.ts_us[i, 0]), mag[i]

    def frames(self) -> Iterator[tuple[int, np.ndarray]]:
        """(ts_us, (n_channels, n_samples)) — all channels per frame."""
        mag = np.abs(self.session.iq).astype(np.float32)
        for i in range(self.session.n_frames):
            yield int(self.session.ts_us[i, 0]), mag[i]

    def __len__(self) -> int:
        return self.session.n_frames


def pe_channel_indices(channels) -> list[int]:
    """Indices of the pulse-echo (tx == rx) channels, in channel order."""
    return [i for i, (tx, rx) in enumerate(channels) if int(tx) == int(rx)]


def pick_stereo_pe(channels, left_sensor: int, right_sensor: int) -> tuple[int, int]:
    """Channel indices for the (left, right) sensors' pulse-echo channels."""
    idx = {int(tx): i for i, (tx, rx) in enumerate(channels) if int(tx) == int(rx)}
    try:
        return idx[left_sensor], idx[right_sensor]
    except KeyError as e:
        raise ValueError(
            f"sensor {e.args[0]} has no pulse-echo channel; available: {sorted(idx)}"
        ) from None


def close_cleanly_on_sigterm() -> None:
    """Make SIGTERM unwind like Ctrl-C, so the board gets closed.

    This is the root cause of the wedge-then-replug cycle that dogged this
    project: KeyboardInterrupt propagates and `with LiveSource(...)` runs its
    __exit__, which stops the measurement and probes the board. SIGTERM does
    not — Python's default handler terminates the process immediately, so the
    rig is left mid-stream and the NEXT open finds identity replies
    interleaved with stale measurement bytes and wedges. Anything that kills
    a bridge or a listener from outside (a launcher tearing down, `kill`, an
    IDE stop button) hits exactly that path.

    Idempotent, and a no-op off the main thread where signal() would raise.
    """
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return

    def _disarm() -> None:
        """Ignore EVERY stop signal, not just the one that arrived.

        Disarming only `signum` left two live routes into the cleanup it was
        meant to protect: Ctrl-C at a launcher sends SIGINT to the whole
        process group AND then the launcher's own handler sends SIGTERM to
        the child microseconds later, straight into the close that the
        SIGINT started; and two impatient Ctrl-Cs do it with no launcher at
        all — the likeliest thing a user does when a close takes seconds and
        prints nothing. SIGKILL stays the escape hatch.
        """
        for s in filter(None, (signal.SIGINT, signal.SIGTERM,
                               getattr(signal, "SIGHUP", None))):
            try:
                signal.signal(s, signal.SIG_IGN)
            except (ValueError, OSError):
                pass

    def _raise(signum, frame):        # noqa: ARG001
        _disarm()
        raise KeyboardInterrupt

    # getattr, not signal.SIGHUP: the attribute does not exist on Windows and
    # building the tuple raised before the try could catch it — which crashed
    # the bridge at startup on the platform the EVK actually ships for.
    # SIGHUP is armed only because a terminal hangup should also close the
    # board; nothing in run/ sends it.
    for sig in filter(None, (signal.SIGTERM, getattr(signal, "SIGHUP", None))):
        try:
            # Never stomp an inherited SIG_IGN — that is what `nohup` sets on
            # SIGHUP, and overriding it would make a nohup'd bridge die on
            # terminal close, which is the opposite of what the user asked
            # for. Same care the SIGINT restore below takes.
            if signal.getsignal(sig) is signal.SIG_IGN:
                continue
            signal.signal(sig, _raise)
        except (ValueError, OSError):
            pass                      # not the main thread on this platform

    # SIGINT gets the same handler, for two reasons.
    #
    # One: a process started in the background inherits SIGINT = SIG_IGN
    # (POSIX job control), so "Ctrl-C to stop" is a lie there and the rig is
    # held until something sends TERM — which is how a replay bridge sat on
    # port 8765 for half an hour in this project's own session.
    #
    # Two, and this is the one that bites in normal use: Python's default
    # SIGINT handler raises KeyboardInterrupt but disarms nothing, so the
    # SECOND stop signal lands inside the cleanup the first one started.
    # Measured — a launcher Ctrl-C (SIGINT to the process group, then the
    # launcher's own SIGTERM to the child) and two impatient Ctrl-Cs both
    # began the close and never finished it. Routing SIGINT through _raise
    # makes the first one disarm the rest.
    #
    # A handler the caller installed deliberately is still left alone.
    try:
        cur = signal.getsignal(signal.SIGINT)
        if cur is signal.default_int_handler or cur is signal.SIG_IGN:
            signal.signal(signal.SIGINT, _raise)
    except (ValueError, OSError):
        pass


class LiveSource:
    """Stream frames from the EVK board.

    Wraps the `ultrasonic` repo's `matrix.runtime.Rig` (board bring-up, flash,
    TX-Opt, phase calibration) and `matrix.frames.assemble_frames`. Must run
    under that repo's `.venv-py39` interpreter — the EVK driver stack is py3.9.

    Two gotchas inherited from upstream, both handled here:
    - `assemble_frames` re-returns the WHOLE rolling buffer every call, so
      frames are deduplicated by timestamp before being yielded.
    - Anything slow in the consumer starves the serial reader thread (the
      documented board-wedging failure), so `poll()` never blocks and the
      caller decides its own pacing.

    Usage:
        with LiveSource("m3x3_txrot_odr13", "/dev/cu.usbmodem11301") as src:
            while True:
                for ts_us, mag in src.poll():   # mag: (n_channels, n_samples)
                    ...
                time.sleep(0.01)
    """

    KEEP_US = 2_000_000  # rolling raw-callback window, same as live_ascan

    #: Two temple sensors: channels [(2,2),(2,3),(3,2),(3,3)], PE at 0 and 3,
    #: 38.5 Hz at odr_ms=13 (one fewer TX slot per rotation than the 3x3 rig).
    DEFAULT_CONFIG = "p2x2_txrot_pair23"

    #: echoears has exactly one capture point: the tx160/233 cm queue.
    #: Its beat is TX 0.91 ms + RX 13.69 ms + SPI readout ~10.5 ms = 25.1 ms,
    #: which does NOT fit 25 — measured clean at 26 ms (19.2 Hz). A bare
    #: LiveSource() used to inherit upstream's 13 ms and fail as readout
    #: starvation, not as an error — so the safe beat is the default here
    #: and None means "this default", not "upstream's". Single source of
    #: truth: apps/live.py and tools/bridge.py default their --odr-ms to
    #: None and land here.
    DEFAULT_ODR_MS = 26

    def __init__(self, config_name: str = DEFAULT_CONFIG,
                 com_port: str | None = None,
                 repo: str | Path = ULTRASONIC_REPO,
                 attempts: int = 3,
                 odr_ms: int | None = None):
        odr_ms = odr_ms or self.DEFAULT_ODR_MS
        self.config_name = config_name
        self.com_port = com_port
        self.repo = Path(repo)
        self.attempts = attempts
        #: Beat interval override. The upstream CaptureConfig is written for
        #: the short 22 cm queue (13 ms); a long-range queue needs a longer
        #: beat or the measurement cannot finish inside it, which shows up as
        #: readout starvation and desynced frames rather than a clean error.
        self.odr_ms = odr_ms
        self.rig = None
        self._frames_mod = None
        self._raw: deque = deque()
        self._last_ts: int = -1
        # filled after the first assembled frame:
        self.channels: list[tuple[int, int]] = []
        self.rx_ids: list[int] = []
        self.fop_hz: np.ndarray | None = None
        self.n_samples: int = 0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "LiveSource":
        """Bring the board up, recovering and retrying if it comes up wedged.

        TX-MUTED and LINK-DEAD are ordinary transient states on this rig, not
        crashes, and upstream ships the fix (`common/evk/recover.py`: API reset
        -> raw soft reset -> LDO power-cycle). So drive it automatically
        instead of telling the user to replug: only a genuinely dead link
        should ever reach a human.
        """
        if sys.version_info[:2] != (3, 9):
            raise RuntimeError(
                f"LiveSource needs the EVK py3.9 stack; this is Python "
                f"{sys.version_info[0]}.{sys.version_info[1]}. Run under "
                f"{self.repo}/.venv-py39/bin/python"
            )
        if not self.repo.is_dir():
            raise FileNotFoundError(f"ultrasonic repo not found at {self.repo}")
        sys.path.insert(0, str(self.repo))

        from common.evk import recover  # noqa: PLC0415
        from matrix import configs, frames, runtime  # noqa: PLC0415

        self._frames_mod = frames
        cfg = configs.get(self.config_name)
        if self.odr_ms and self.odr_ms != cfg.odr_ms:
            import dataclasses  # noqa: PLC0415
            cfg = dataclasses.replace(cfg, odr_ms=self.odr_ms)
        port = self.com_port or self._autoport()
        print(f"[live] config={cfg.name}  odr_ms={cfg.odr_ms}  "
              f"({1000/(cfg.n_tx*cfg.odr_ms):.1f} Hz)  port={port}")

        last = ""
        for attempt in range(1, self.attempts + 1):
            if attempt > 1:
                print(f"\n[live] 自动救板 (第 {attempt}/{self.attempts} 次尝试) ...")
                if not recover.auto_recover(port):
                    print("[live] 恢复阶梯跑完仍无响应 — 需要物理拔插 USB")
                    break
                time.sleep(1.0)
            try:
                # assign BEFORE open(): if the flash (10-30 s) is interrupted,
                # close() must still be able to reach the Rig. Constructing it
                # is cheap and does not touch the port; open() is what does.
                self.rig = runtime.Rig(cfg, port)
                self.rig.open()
                ok, iters = self.rig.calibrate()
                if ok:
                    print(f"[live] calibrated in {iters} iters; streaming")
                    self.rig.handler.take()  # drop the calibration leftovers
                    return self
                last = "phase calibration failed"
            except Exception as e:  # noqa: BLE001 — bring-up throws many types
                # A sensor-set mismatch is a CONFIG error, not a wedged board.
                # Resetting hardware cannot conjure a sensor that is not
                # plugged in, and hammering a healthy board with the recovery
                # ladder is how you actually wedge it. Fail fast instead.
                if "!=" in str(e) and "sensors" in str(e):
                    self.close()
                    raise RuntimeError(self._config_hint(e, configs)) from None
                last = f"{type(e).__name__}: {e}"
                print(f"[live] 起板失败: {last}")
            except BaseException:
                # KeyboardInterrupt (incl. a remapped SIGTERM) is NOT an
                # Exception, so without this the longest window in the
                # program — the 10-30 s flash the user is told to wait
                # through — got no cleanup at all, and `with LiveSource(...)`
                # cannot help because Python skips __exit__ when __enter__
                # raises. This is exactly when an impatient user hits stop.
                print("\n[live] 起板期间被中断 — 收板中 ...")
                self.close()
                raise
            # Rig.close() runs its own auto-recover when the stop write failed.
            self.close()

        raise RuntimeError(
            f"{last} — 已自动重试 {self.attempts} 次并跑过恢复阶梯(API 复位 / "
            f"软复位 / LDO 断电重上电)仍未成功"
        )

    @staticmethod
    def _config_hint(err: Exception, configs) -> str:
        """Turn 'sensors [2, 3] != config (0, 2, 3)' into an actionable message."""
        found = re.search(r"sensors \[([^\]]*)\]", str(err))
        ids = tuple(int(x) for x in found.group(1).split(",") if x.strip()) if found else ()
        match = next((c.name for c in getattr(configs, "CONFIGS", {}).values()
                      if tuple(sorted(c.sensor_ids)) == tuple(sorted(ids))), None)
        msg = [f"板子上实际连着的传感器是 {list(ids)},和当前配置对不上。",
               "这是配置问题,不是板子坏了 —— 不会去复位硬件。"]
        if match:
            msg.append(f"用 --config {match} 就对了。")
        else:
            msg.append("没有现成配置匹配这个传感器组合;"
                       "在上游 matrix/configs.py 里加一个 CaptureConfig。")
        return "  " + "\n  ".join(msg)

    def _autoport(self) -> str:
        import glob
        hits = sorted(glob.glob("/dev/cu.usbmodem*"))
        if not hits:
            raise FileNotFoundError("no /dev/cu.usbmodem* — is the board plugged in?")
        return hits[0]

    def close(self):
        if self.rig is not None:
            port = getattr(self.rig, "com_port", None)
            self.rig.close()
            self.rig = None
            # Three sessions in a row ended with the NEXT open finding the
            # board mid-stream (identity replies interleaved with stale
            # measurement bytes -> header mismatch -> wedge, replug needed).
            # Upstream stop() can fail silently, so verify the board actually
            # answers now, while a recovery still has a serial port to use.
            # NOTE: not yet verified against a real wedge — first hardware
            # session after this change should watch for the probe message.
            if port:
                try:
                    from common.evk import recover
                    if not recover.try_open(port):   # two-open health check
                        print("[live] 板子关门后不应答 — 现场救板,免得下次打不开")
                        recover.auto_recover(port)
                except Exception as e:  # noqa: BLE001
                    print(f"[live] close-probe: {e}")

    def __enter__(self) -> "LiveSource":
        return self.start()

    def __exit__(self, *exc):
        self.close()
        return False

    # -- streaming ---------------------------------------------------------
    @property
    def frame_hz(self) -> float:
        cfg = self.rig.config
        return 1000.0 / (cfg.n_tx * cfg.odr_ms)

    def range_axis(self, ch: int, *, smclk_per_sample: int) -> np.ndarray:
        tx, rx = self.channels[ch]
        fop = float(self.fop_hz[self.rx_ids.index(rx)])
        # live capture always runs the tx160 queue -> axis starts ~15.5 cm out
        return prof.range_axis_raw(tx, rx, fop, self.n_samples,
                                   smclk_per_sample=smclk_per_sample,
                                   tx_smclk=prof.LIVE_TX_SMCLK)

    def poll(self) -> list[tuple[int, np.ndarray]]:
        """Drain the driver queue; return only frames not yielded before.

        Non-blocking. Each item is (ts_us, |IQ| (n_channels, n_samples)).
        """
        for e in self.rig.handler.take():
            self._raw.append(e)
        if not self._raw:
            return []
        newest = self._raw[-1][0]
        while self._raw and newest - self._raw[0][0] > self.KEEP_US:
            self._raw.popleft()

        asm = self._frames_mod.assemble_frames(list(self._raw), self.rig.ids)
        if asm["iq"] is None:
            return []

        if not self.channels:  # first assembled batch: latch geometry
            self.channels = [tuple(int(v) for v in c) for c in asm["channels"]]
            self.rx_ids = list(self.rig.ids)
            self.fop_hz = np.asarray(asm["fop_hz"], dtype=float)
            self.n_samples = int(asm["iq"].shape[2])

        out = []
        for i, ts in enumerate(asm["ts_us"][:, 0]):
            ts = int(ts)
            if ts <= self._last_ts:  # whole-buffer re-return: dedup
                continue
            self._last_ts = ts
            out.append((ts, np.abs(asm["iq"][i]).astype(np.float32)))
        return out
