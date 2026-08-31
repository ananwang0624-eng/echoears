"""Live source running the VENDOR rangefinder firmware, not txrot.

Two sensors, pulse-echo only, Long Range measurement sequence, TX
optimisation on. The on-chip algorithm reports up to 5 targets per beat as
(range, amplitude) and we sonify those directly — no host-side peak
picking, no clutter removal, no sigma normalisation.

What this trades away, stated once so nobody rediscovers it the hard way:
the ICU-10201 has ONE algo slot. Loading gpt evicts txrot, and with txrot
goes TX rotation — so there is no 2x2 pitch-catch matrix here, only the two
pulse-echo channels. That is the whole cost, and it is why this lives
beside the txrot path rather than replacing it. Switching back is automatic:
every open() programs the firmware it wants, so run/8 restores txrot.

Why it can be worth paying: the vendor rule answers "what IS there" against
an absolute threshold, so a wall you are standing still in front of keeps
reporting. The txrot path removes static clutter first and therefore
answers "what CHANGED", which goes silent when you stop moving.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

ULTRASONIC_REPO = Path.home() / "Documents" / "GitHub" / "ultrasonic"

#: Vendor preset directory (relative to the pysonic package root) and the
#: presets in it. They differ in what the on-chip threshold rule is tuned
#: for — the choice decides what a "target" is:
#:   long    Long Range.json — ODR 2 (3.1 cm/bin, reach ~5.6 m), near
#:           thresholds 1600/800 counts: built for walls at 2-5 m, nearly
#:           blind to a palm inside 80 cm.
#:   short   Short Range.json — ODR 6 (~1 cm/bin), 60-135 cm at only 200
#:           counts, stepped-down TX for a shorter ringdown: palm-friendly.
#:   static  Static Target Rejection.json — like the txrot ethos, reports
#:           what CHANGED.
#:   default defaults.json.
CFG_DIR = "plugins/config/rangefinder/icu-10201"
PRESETS = {
    "long": "Long Range.json",
    "short": "Short Range.json",
    "static": "Static Target Rejection.json",
    "default": "defaults.json",
}


def cfg_cic_odr(path) -> int:
    """CIC ODR of a preset — sets the range-axis bin width, so the bridge
    must read it from the file rather than assume Long Range's 2."""
    import json
    return int(json.loads(Path(path).read_text())["meas"][0]["odr"])

#: MAXTARG in ch-rangefinder/structs.h. Only the first
#: `num_valid_targets` entries are meaningful — the rest of the array is
#: uninitialised and reads as plausible-looking garbage (range 0 with
#: amplitudes in the tens of thousands), so it MUST be truncated.
MAX_TARGETS = 5

#: Beat interval for the Long Range sequence, chosen by sweeping the real
#: rig rather than by arithmetic — the arithmetic was wrong twice.
#: Measured, 6 s per setting, two sensors, callbacks / target-bearing
#: frames / peak IQ:
#:     odr_ms 26   IllegalSampleRate, IQ all zeros, targets present
#:     odr_ms 35   21.5 Hz/sensor, 54 target frames, IQ peak 1602   <- use
#:     odr_ms 70   19.1 Hz/sensor,  0 target frames, IQ peak 1144
#: 70 was my estimate from "two sensors x 31.4 ms of listening"; it produces
#: waveforms but the algorithm stops reporting, so the estimate was not
#: measuring what I thought it was.
ODR_MS_LONG_RANGE = 35


def _make_handler(base_cls):
    class RangeHandler(base_cls):
        def __init__(self):
            super().__init__(device_log_file=None,
                             show_uart_traces_from_device=False,
                             handle_algo_data=True)     # the whole point
            # RLock, not Lock: ch_data_handler and dict_handler both take
            # it, and the vendor stack is free to dispatch one from inside
            # the other. A plain Lock deadlocks the callback thread there,
            # which presents as zero events — no error, no data, nothing.
            self.lock = threading.RLock()
            self.events = []
            self.exc = {}

        def ch_data_handler(self, rx_sensor_id, tx_sensor_id, timestamp,
                            idata, qdata, target_detected, range_cm, amplitude,
                            m_per_range_lsb=None, pmut_frequency=None,
                            meas_queue=None):
            iq = (np.asarray(idata, dtype=np.float32)
                  + 1j * np.asarray(qdata, dtype=np.float32)).astype(np.complex64)
            # range_cm and amplitude arrive as LISTS, one entry per detected
            # target — [55.64] and [423] on a real hit, [] on a miss. The
            # probe output said so and I read it as scalars; float() on a
            # list then raised on EVERY callback, and the exception handler
            # counted it silently, so a working board looked like a dead one.
            # Metres here, unlike the ch_data_handler docstring's "cm".
            rngs = list(range_cm or []) if isinstance(range_cm, (list, tuple)) \
                else ([] if range_cm is None else [range_cm])
            amps = list(amplitude or []) if isinstance(amplitude, (list, tuple)) \
                else ([] if amplitude is None else [amplitude])
            with self.lock:
                self.events.append({
                    "ts": int(timestamp), "sid": int(rx_sensor_id), "iq": iq,
                    "fop": float(pmut_frequency or 0.0),
                    "detected": bool(target_detected),
                    # (cm, amplitude) pairs straight off the convenience
                    # fields; dict_handler overwrites this with the full
                    # target list when it also fires for this beat
                    "targets": [(float(r) * 100.0, float(a))
                                for r, a in zip(rngs, amps) if float(r) > 0],
                })

        def dict_handler(self, timestamp, algo_data, **meta):
            """Full target list: algo_data['tL']['targets'][i]['range'|
            'amplitude'], already converted to metres by the vendor stack."""
            tl = (algo_data or {}).get("tL") or {}
            n = int(tl.get("num_valid_targets", 0) or 0)
            tgs = tl.get("targets") or []
            # slots past num_valid_targets hold uninitialised memory —
            # observed range 0 with amplitude 45347. Truncating is not an
            # optimisation, it is the difference between targets and noise.
            out = [(float(t["range"]) * 100.0, float(t["amplitude"]))
                   for t in tgs[:min(n, MAX_TARGETS)]
                   if float(t["range"]) > 0.0]
            sid = meta.get("rx_sensor_id", meta.get("sensor_id"))
            with self.lock:
                # attach to the most recent event of this sensor
                for ev in reversed(self.events):
                    if sid is None or ev["sid"] == int(sid):
                        ev["targets"] = out
                        break

        def take(self):
            with self.lock:
                out, self.events = self.events, []
            return out

        def __getattr__(self, name):
            """Absorb every handler the vendor stack looks for.

            The probe script that DID stream had exactly this catch-all and
            this class did not, which is the only structural difference
            between them. A missing `*_handler` attribute is not a warning
            deep in that stack — it can stop delivery entirely.
            """
            if name.endswith("_handler") or name.startswith("write_"):
                return lambda *a, **k: None
            raise AttributeError(name)

        def exception_handler(self, e):
            s = repr(e)
            if "write_algo_data" in s or "algo_data_writer" in s:
                return
            with self.lock:
                k = s.split("(")[0]
                first = k not in self.exc
                self.exc[k] = self.exc.get(k, 0) + 1
            if first:
                # print the FIRST of each kind with its traceback. Counting
                # silently is how a handler that raised on every single
                # callback looked exactly like a board delivering nothing.
                import traceback
                print(f"[range] handler exception ({k}):", flush=True)
                traceback.print_exception(type(e), e, e.__traceback__)

    return RangeHandler


class RangeSource:
    """Vendor rangefinder firmware, two sensors, pulse-echo only."""

    def __init__(self, com_port: str | None = None,
                 sensor_ids: tuple[int, ...] = (2, 3),
                 odr_ms: int | None = None,
                 attempts: int = 3,
                 repo: str | Path = ULTRASONIC_REPO,
                 cfg: str = "long"):
        self.com_port = com_port
        self.sensor_ids = tuple(sensor_ids)
        # 35 was measured for Long Range; Short Range's meas_period is
        # smaller (800 vs 3000), so the same interval is a safe floor there.
        self.odr_ms = int(odr_ms or ODR_MS_LONG_RANGE)
        self.cfg = cfg
        self.cic_odr: int | None = None      # set at start, read from the cfg
        self.attempts = int(attempts)
        self.repo = Path(repo)
        self.device = None
        self.handler = None
        self.dc = None
        self.ids: list[int] = []
        self.n_samples = 0
        self.fop_hz: dict[int, float] = {}
        self._ch_seen = 0
        self._targets_seen = 0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "RangeSource":
        """Bring the rig up, with the same recovery ladder LiveSource has.

        Repeated firmware flashes wedge this board — it happened three times
        while this path was being written, always mid-OTP-read — and without
        a ladder every wedge costs a physical replug.
        """
        import sys
        if str(self.repo) not in sys.path:
            sys.path.insert(0, str(self.repo))
        from common.evk import recover

        last = ""
        for attempt in range(1, self.attempts + 1):
            if attempt > 1:
                print(f"\n[range] auto-recovery (attempt {attempt}/{self.attempts}) ...")
                if not recover.auto_recover(self._port()):
                    print("[range] recovery ladder exhausted — replug the USB cable")
                    break
                time.sleep(1.0)
            try:
                return self._start_once()
            except BaseException as e:          # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
                print(f"[range] bring-up failed: {last.splitlines()[0][:120]}")
                self.close()
                if isinstance(e, KeyboardInterrupt):
                    raise
        raise RuntimeError(f"{last} — retried {self.attempts} times through the recovery ladder")

    def _port(self) -> str:
        if self.com_port:
            return self.com_port
        import glob
        hits = sorted(glob.glob("/dev/cu.usbmodem*"))
        return hits[0] if hits else ""

    def _start_once(self) -> "RangeSource":
        import sys
        if str(self.repo) not in sys.path:
            sys.path.insert(0, str(self.repo))
        from common.evk import bootstrap as evk
        from invn.pysonic.cmlogger import PysonicEventHandler

        fw = evk.plugins_metadata["gpt"]["default_fw_path"]
        name = PRESETS.get(str(self.cfg).lower(), str(self.cfg))
        cfg = Path(name) if Path(name).is_absolute() \
            else self._plugin_root() / CFG_DIR / name
        if not cfg.is_file():
            raise RuntimeError(
                f"preset not found: {cfg} — use one of {sorted(PRESETS)} "
                f"or an absolute path")
        self.cic_odr = cfg_cic_odr(cfg)

        print(f"[range] fw=gpt ({Path(fw).name})")
        print(f"[range] cfg={cfg.name}  sensors={list(self.sensor_ids)}  "
              f"odr_ms={self.odr_ms}")
        self.handler = _make_handler(PysonicEventHandler)()
        self.dc = evk.open_dc(self.com_port, self.handler)
        shield = evk.ShastaEVKBoard(self.dc, dac_spi_baudrate=2,
                                    dut_spi_baudrate=2, use_leds=True)
        self.device = evk.RedswallowLink(
            self.dc, shield, meas_queues=None, fw_path=fw,
            reg_fmt_path=None, enable_invntrack=False,
            use_init_fw=True, run_tx_opt=True)      # TX optimisation ON
        # Stale callbacks from a previous python process are already handled:
        # open_dc() above calls dc.clearActionStack() right after dc.open(),
        # which is the placement every validated script in the upstream repo
        # uses (common/evk/bootstrap.py, first diagnosed 2026-05-28 as
        # "GPIO timeout / callback_id N already registered").

        print("[range] programming (10-30s flash) ...")
        self.device._detect_program_and_init()
        cs = self.device.connected_sensors
        self.ids = sorted(cs["sensor_ids"] if isinstance(cs, dict) else cs)
        print(f"[range] connected sensors = {self.ids}")
        if tuple(self.ids) != self.sensor_ids:
            raise RuntimeError(
                f"sensors {self.ids} != expected {list(self.sensor_ids)} — "
                f"this path is pulse-echo only, one channel per sensor")

        # Mode 1 = pulse-echo round-robin: every sensor TXes and RXes its own
        # beat — the "two pulse-echo channels" this module promises. This is
        # also what the one recording that ever streamed under gpt used
        # (IcuPlugins.GPT.toml: sensors_trigger_mode=1, all sensors report).
        # Mode 0 is STATIC PITCH-CATCH (one TX, everyone listens), and the
        # GUI's _set_sensors_trigger_mode shows that selecting it takes four
        # calls (mode, disable_transmitter, enable_transmitter([tx]),
        # send_meas_queue); a bare setSensorsTriggerMode(0) — what this line
        # used to do — leaves host and board disagreeing about who transmits.
        self.device.setSensorsTriggerMode(1)
        # Call send_cfg_bist per sensor rather than going through
        # send_meas_queue. Its body is
        #     sensor.send_cfg_bist(self.dc, mq_writers[sensor.index], ...)
        # and `sensor.index` is the bus position, not an offset into the
        # list you pass — with sensors at ids 2 and 3 a 2-element
        # mq_writers is indexed at [2] and raises IndexError inside the
        # vendor code. Addressing sensors by id sidesteps the question:
        # _get_sensor_by_id is the accessor the upstream repo already uses,
        # and `dc` is the `board` argument the vendor passes itself.
        #
        # run_tx_opt=True is what triggers EVENT_TX_OPTIMIZE after the queue
        # lands, i.e. "TX Opt on" for this part.
        for sid in self.ids:
            sensor = self.device._get_sensor_by_id(sid)
            print(f"[range] sensor {sid} (index {getattr(sensor, 'index', '?')})"
                  f" <- {cfg.name}, TX opt on")
            sensor.send_cfg_bist(self.device.dc, str(cfg),
                                 run_tx_opt=True, trigger_algo_init=True)
        self.device.odr_ms = self.odr_ms
        # No enableIQStream() call: RedswallowLink.enableIQStream is
        # literally `logger.debug('enableIQStream does nothing')` — a no-op
        # kept for API compatibility. Whether IQ streams is decided by the
        # meas queue's iq_output_format, which is 0 (= stream (Q,I) pairs)
        # in the Long Range preset. The "IQ all zeros without it" this file
        # used to claim was the odr_ms=26 IllegalSampleRate confound, not
        # IQ enablement.
        #
        # startDeviceProcessing goes DEAD LAST, matching the GUI's
        # _apply_config ordering. No settling poll after it — that silently
        # eats the first frames the caller is waiting for.
        self.device.startDeviceProcessing()
        return self

    def wait_for_data(self, timeout_s: float = 15.0) -> "RangeSource":
        """Block until the first assembled frame, or say what is missing.

        Spinning forever on `while not n_samples` was worse than useless:
        the bridge never published its meta, so the browser could not even
        connect and the failure presented as "no waveform".
        """
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            self.poll()
            if self.n_samples:
                return self
            time.sleep(0.02)
        exc = getattr(self.handler, "exc", {})
        raise RuntimeError(
            f"no IQ frames in {timeout_s:.0f} s. Targets seen: "
            f"{self._targets_seen}; channel callbacks: {self._ch_seen}; "
            f"handler exceptions: {exc or 'none'}. "
            f"If targets arrive but IQ does not, check the queue's "
            f"iq_output_format (must be 0) and odr_ms (26 gave all-zero IQ).")

    @staticmethod
    def _plugin_root() -> Path:
        import invn.pysonic as ps
        return Path(ps.__file__).resolve().parent

    def close(self):
        if self.device is not None:
            try:
                self.device.stopDeviceProcessing()
            except Exception as e:                    # noqa: BLE001
                print(f"[range] stop failed (non-fatal): {e}")
            # Whether or not the stop landed, drop our callbacks so the next
            # process is not fed into ours. Skipping this is what leaves the
            # board streaming into a dead interpreter. On dc — the object
            # that owns the action stack — not on device.
            try:
                if self.dc is not None:
                    self.dc.clearActionStack()
            except Exception:                         # noqa: BLE001
                pass
            try:
                if self.dc is not None:
                    self.dc.close()
            except Exception:                         # noqa: BLE001
                pass
            self.device = None

    def __enter__(self) -> "RangeSource":
        return self.start()

    def __exit__(self, *exc):
        self.close()
        return False

    # -- streaming ---------------------------------------------------------
    @property
    def frame_hz(self) -> float:
        # Round-robin (trigger mode 1) shares the schedule: each sensor
        # beats every n_sensors * odr_ms. The board's own reference-timer
        # config confirms it (period 70000 us, stagger 35000 us at odr 35),
        # and the assembled-frame rate measured end-to-end is 14.3 Hz.
        return 1000.0 / (self.odr_ms * max(1, len(self.ids or self.sensor_ids)))

    def poll(self) -> list[dict]:
        """Drain the handler. Each item is one sensor's beat: iq, targets."""
        evs = self.handler.take() if self.handler else []
        self._ch_seen += len(evs)
        self._targets_seen += sum(1 for e in evs if e["targets"])
        for ev in evs:
            if ev["iq"].size:
                self.n_samples = int(ev["iq"].shape[-1])
            if ev["fop"]:
                self.fop_hz[ev["sid"]] = ev["fop"]
        return evs
