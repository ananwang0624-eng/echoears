"""Unit tests — pure functions only, no hardware, no recorded files needed."""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echoears import profile as prof
from echoears import sonify as son
from echoears.session import SOUND_CM_S, Session


def fake_session(n_frames=8, n_samples=115, fop=175000.0) -> Session:
    ids = [0, 2, 3]
    channels = np.array([[t, r] for t in ids for r in ids], dtype=np.int64)
    rng = np.random.default_rng(0)
    iq = (rng.normal(size=(n_frames, 9, n_samples))
          + 1j * rng.normal(size=(n_frames, 9, n_samples))).astype(np.complex64)
    ts = (np.arange(n_frames) * 39_000).astype(np.int64)[:, None].repeat(3, axis=1)
    return Session(iq=iq, ts_us=ts, channels=channels,
                   rx_ids=np.array(ids, dtype=np.int64),
                   fop_hz=np.full(3, fop))


# --- range axis: the part that is easy to get silently wrong ---------------

def test_odr_table_matches_vendor_formula():
    for odr, smclk in prof.ODR_SMCLK_PER_SAMPLE.items():
        assert smclk == 16 * 2 ** (7 - odr)


def test_pulse_echo_axis_is_half_of_pitch_catch():
    s = fake_session()
    pe = prof.range_axis(s, 0, smclk_per_sample=32)   # (0,0) -> tx == rx
    pc = prof.range_axis(s, 1, smclk_per_sample=32)   # (0,2) -> tx != rx
    assert np.allclose(pc, 2 * pe)


def test_current_config_covers_22cm():
    """odr=6, 115 samples, fop 175 kHz -> the documented 22.5 cm / 45 cm."""
    s = fake_session()
    pe = prof.range_axis(s, 0, smclk_per_sample=32)
    pc = prof.range_axis(s, 1, smclk_per_sample=32)
    assert pe[-1] == pytest.approx(22.54, abs=0.05)
    assert pc[-1] == pytest.approx(45.08, abs=0.05)


def test_range_scales_with_smclk_not_with_sample_count():
    """ODR sets resolution; doubling SMCLK/sample doubles reach at fixed n."""
    s = fake_session()
    a = prof.range_axis(s, 0, smclk_per_sample=32)[-1]
    b = prof.range_axis(s, 0, smclk_per_sample=64)[-1]
    assert b == pytest.approx(2 * a)


def test_rx_smclk_round_trips_with_max_range():
    """The listening window is what buys range — check the two agree."""
    fop = 175000.0
    smclk = prof.rx_smclk_for_range(120.0, fop, pulse_echo=True)
    n = smclk // 128                       # at odr=4
    got = prof.max_range_cm(n, fop, smclk_per_sample=128, pulse_echo=True)
    assert got == pytest.approx(120.0, rel=0.01)
    assert n <= prof.IQ_SAMPLES_MAX


def test_smclk_for_odr_rejects_bad_input():
    with pytest.raises(ValueError):
        prof.smclk_for_odr(9)


# --- profile ops -----------------------------------------------------------

def test_remove_static_kills_a_constant_and_keeps_a_transient():
    mag = np.ones((20, 115), dtype=np.float32) * 100.0
    mag[10, 40] += 500.0
    out = prof.remove_static(mag)
    assert out.max() == pytest.approx(500.0, rel=0.01)
    assert np.argmax(out) % 115 == 40
    assert out[0].max() == 0.0            # the constant floor is gone
    assert (out >= 0).all()               # clipped, never negative


def test_normalize_handles_all_zero():
    z = np.zeros(10)
    assert not np.isnan(prof.normalize(z)).any()


# --- sonification ----------------------------------------------------------

def test_sonify_length_follows_frames_and_speed():
    mag = np.abs(np.random.default_rng(1).normal(size=(10, 115)))
    a = son.sonify(mag, frame_hz=25.6, sr=44100, speed=1.0)
    b = son.sonify(mag, frame_hz=25.6, sr=44100, speed=0.5)
    assert len(b) == pytest.approx(2 * len(a), rel=0.01)
    assert len(a) == pytest.approx(10 / 25.6 * 44100, rel=0.01)


def test_sonify_is_click_free_at_grain_boundaries():
    """Continuous carrier phase: no sample-to-sample jump beyond the envelope."""
    mag = np.ones((6, 115))
    a = son.sonify(mag, frame_hz=25.6, sr=44100)
    grain = int(round(44100 / 25.6))
    jumps = np.abs(np.diff(a))
    boundary = jumps[[grain - 1, 2 * grain - 1, 3 * grain - 1]]
    assert boundary.max() <= jumps.mean() * 8


def test_sonify_rejects_wrong_shape():
    with pytest.raises(ValueError):
        son.sonify(np.zeros(115), frame_hz=25.6)


def test_write_wav_roundtrip(tmp_path):
    audio = np.sin(np.linspace(0, 100, 4410)).astype(np.float32)
    p = son.write_wav(tmp_path / "t.wav", audio, sr=44100)
    with wave.open(str(p)) as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 44100
        assert w.getnframes() == 4410


def test_write_wav_stereo(tmp_path):
    a = np.stack([np.zeros(1000), np.ones(1000) * 0.5], axis=1)
    p = son.write_wav(tmp_path / "s.wav", a)
    with wave.open(str(p)) as w:
        assert w.getnchannels() == 2


def test_speed_of_sound_constant():
    assert SOUND_CM_S == 34300.0


# --- live-path helpers ------------------------------------------------------

def test_pick_stereo_pe_finds_temple_pair():
    from echoears.sources import pe_channel_indices, pick_stereo_pe
    chans = [(t, r) for t in (0, 2, 3) for r in (0, 2, 3)]
    assert pe_channel_indices(chans) == [0, 4, 8]
    assert pick_stereo_pe(chans, 2, 3) == (4, 8)
    with pytest.raises(ValueError):
        pick_stereo_pe(chans, 2, 7)


def test_running_baseline_learns_clutter_and_passes_transients():
    base = prof.RunningBaseline(alpha=0.1)
    clutter = np.full(115, 100.0, dtype=np.float32)
    for _ in range(200):
        base(clutter)
    quiet = base(clutter)
    assert quiet.max() < 1.0                      # clutter fully absorbed
    hit = clutter.copy(); hit[60] += 400.0
    res = base(hit)
    assert res[60] == pytest.approx(400.0, rel=0.05)
    assert res[:59].max() < 1.0


def test_grain_synth_is_click_free_across_calls():
    g = son.GrainSynth(sr=44100)
    grain = 1723
    a = g.render(np.ones(115), grain)
    b = g.render(np.ones(115), grain)
    joined = np.concatenate([a, b])
    jumps = np.abs(np.diff(joined))
    assert jumps[grain - 1] <= jumps.mean() * 8   # boundary no worse than body


def test_grain_synth_silence_in_silence_out():
    g = son.GrainSynth()
    g.render(np.ones(115) * 500, 1000)            # set the peak tracker
    out = g.render(np.zeros(115), 1000)
    assert np.abs(out).max() < 1e-6


def test_replay_frames_yields_all_channels():
    from echoears.sources import ReplaySource
    # build via the fake session by monkeypatching load
    import echoears.sources as srcmod
    s = fake_session(n_frames=5)
    srcmod_load = srcmod.load
    try:
        srcmod.load = lambda p: s
        rs = ReplaySource("fake.npz", smclk_per_sample=32)
        frames = list(rs.frames())
        assert len(frames) == 5
        ts0, mag0 = frames[0]
        assert mag0.shape == (9, 115)
        assert mag0.dtype == np.float32
    finally:
        srcmod.load = srcmod_load


# --- board bring-up retry ---------------------------------------------------

def _fake_stack(monkeypatch, rig_cls, recover_fn):
    """Install fake `matrix.*` and `common.evk.recover` modules.

    `from matrix import runtime` reads an ATTRIBUTE off the parent package, so
    stubbing sys.modules alone is not enough — the parent must carry them.
    """
    import types
    matrix = types.ModuleType("matrix")
    matrix.runtime = types.SimpleNamespace(Rig=rig_cls)
    matrix.frames = types.ModuleType("frames")
    # a real dataclass, not SimpleNamespace: LiveSource now defaults the
    # beat to 26 ms and rewrites the config via dataclasses.replace()
    import dataclasses as _dc

    @_dc.dataclass
    class _FakeCfg:
        name: str
        n_tx: int = 3
        odr_ms: int = 13

    matrix.configs = types.SimpleNamespace(get=lambda n: _FakeCfg(n))
    common = types.ModuleType("common")
    common.evk = types.ModuleType("evk")
    common.evk.recover = types.SimpleNamespace(auto_recover=recover_fn)
    for name, mod in [("matrix", matrix), ("matrix.runtime", matrix.runtime),
                      ("matrix.frames", matrix.frames),
                      ("matrix.configs", matrix.configs),
                      ("common", common), ("common.evk", common.evk),
                      ("common.evk.recover", common.evk.recover)]:
        monkeypatch.setitem(sys.modules, name, mod)

    from echoears import sources as srcmod
    monkeypatch.setattr(sys, "version_info", (3, 9, 0, "final", 0))
    monkeypatch.setattr(srcmod.time, "sleep", lambda _s: None)
    return srcmod


def _rig_factory(calls, succeed_on):
    import types

    class FakeRig:
        def __init__(self, cfg, port):
            calls["open"] += 1
            self.ids = [0, 2, 3]
            self.config = cfg
            self.handler = types.SimpleNamespace(take=lambda: [])

        def open(self):
            return self

        def calibrate(self):
            return (calls["open"] >= succeed_on, 1)

        def close(self):
            calls["close"] += 1

    return FakeRig


def test_live_source_retries_and_recovers(monkeypatch):
    """A wedged board must run the recovery ladder and retry, not give up."""
    calls = {"open": 0, "recover": 0, "close": 0}

    def rec(_port):
        calls["recover"] += 1
        return True

    srcmod = _fake_stack(monkeypatch, _rig_factory(calls, succeed_on=3), rec)
    src = srcmod.LiveSource("cfg", "/dev/fake", attempts=3)
    src.start()

    assert calls["open"] == 3      # brought up three times
    assert calls["recover"] == 2   # ladder ran before each retry
    assert calls["close"] == 2     # the two failed rigs were closed


def test_live_source_gives_up_after_attempts(monkeypatch):
    calls = {"open": 0, "recover": 0, "close": 0}
    srcmod = _fake_stack(monkeypatch, _rig_factory(calls, succeed_on=99),
                         lambda _p: True)
    src = srcmod.LiveSource("cfg", "/dev/fake", attempts=2)
    with pytest.raises(RuntimeError, match="retried 2 times"):
        src.start()
    assert calls["open"] == 2


def test_live_source_stops_when_ladder_cannot_revive_board(monkeypatch):
    """If recovery itself reports failure, stop — do not keep hammering."""
    calls = {"open": 0, "recover": 0, "close": 0}
    srcmod = _fake_stack(monkeypatch, _rig_factory(calls, succeed_on=99),
                         lambda _p: False)
    src = srcmod.LiveSource("cfg", "/dev/fake", attempts=5)
    with pytest.raises(RuntimeError):
        src.start()
    assert calls["open"] == 1      # gave up instead of retrying blindly


def test_default_config_is_the_two_sensor_temple_pair():
    """Guard against silently reverting to the 3-sensor bench template."""
    from echoears.sources import LiveSource
    assert LiveSource.DEFAULT_CONFIG == "p2x2_txrot_pair23"


def test_two_sensor_channel_layout_puts_ears_at_0_and_3():
    from echoears.sources import pe_channel_indices, pick_stereo_pe
    chans = [(t, r) for t in (2, 3) for r in (2, 3)]   # 4 channels, not 9
    assert len(chans) == 4
    assert pe_channel_indices(chans) == [0, 3]
    assert pick_stereo_pe(chans, 2, 3) == (0, 3)


def test_config_hint_names_the_matching_config(monkeypatch):
    """A sensor mismatch must suggest a config, not trigger hardware recovery."""
    import types
    from echoears.sources import LiveSource
    fake_configs = types.SimpleNamespace(CONFIGS={
        "m3x3_txrot_odr13": types.SimpleNamespace(
            name="m3x3_txrot_odr13", sensor_ids=(0, 2, 3)),
        "p2x2_txrot_pair23": types.SimpleNamespace(
            name="p2x2_txrot_pair23", sensor_ids=(2, 3)),
    })
    err = Exception("sensors [2, 3] != config (0, 2, 3)")
    hint = LiveSource._config_hint(err, fake_configs)
    assert "p2x2_txrot_pair23" in hint
    assert "not a broken board" in hint


def test_sensor_mismatch_does_not_run_recovery(monkeypatch):
    """The ladder must not fire for a config error — that is how boards wedge."""
    import types
    calls = {"recover": 0, "open": 0}

    class MismatchRig:
        def __init__(self, cfg, port):
            calls["open"] += 1
            self.ids = [2, 3]
            self.config = cfg
            self.handler = types.SimpleNamespace(take=lambda: [])

        def open(self):
            raise Exception("sensors [2, 3] != config (0, 2, 3)")

        def close(self):
            pass

    def rec(_p):
        calls["recover"] += 1
        return True

    srcmod = _fake_stack(monkeypatch, MismatchRig, rec)
    srcmod.sys.modules["matrix"].configs.CONFIGS = {
        "p2x2_txrot_pair23": types.SimpleNamespace(
            name="p2x2_txrot_pair23", sensor_ids=(2, 3))}
    src = srcmod.LiveSource("wrong", "/dev/fake", attempts=3)
    with pytest.raises(RuntimeError, match="p2x2_txrot_pair23"):
        src.start()
    assert calls["open"] == 1      # failed once
    assert calls["recover"] == 0   # and did NOT reset the board


# --- web export round-trip --------------------------------------------------

def _load_module(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = Path(__file__).resolve().parents[1]


def test_web_raw_encode_decode_round_trips():
    """--raw still ships log-compressed counts, and data.js must invert it."""
    ew = _load_module("export_web", REPO / "tools" / "export_web.py")
    mag = np.array([[[0.0, 1.0, 10.0, 500.0, 7000.0]]], dtype=np.float32)
    codes, peak = ew._encode_raw(mag)
    assert codes.dtype == np.uint8
    assert codes.max() == 255                       # the peak maps to full scale

    # mirror of the counts branch in web/js/data.js
    log_peak = np.log10(1 + peak)
    back = np.where(codes == 0, 0.0, 10 ** (codes / 255 * log_peak) - 1)
    assert back.flat[-1] == pytest.approx(7000.0, rel=0.02)
    assert back.flat[0] == 0.0
    assert back.flat[3] == pytest.approx(500.0, rel=0.05)


def test_web_encode_handles_all_zero():
    ew = _load_module("export_web", REPO / "tools" / "export_web.py")
    assert ew.encode(np.zeros((2, 2, 8))).max() == 0        # sigma path
    codes, peak = ew._encode_raw(np.zeros((2, 2, 8), dtype=np.float32))
    assert codes.max() == 0 and peak >= 1.0                 # no NaN, no /0


def test_plan_models_the_rx_window_not_just_readout():
    """Range is bounded by the beat, and the beat includes time spent listening.

    Regression: the planner used to cost only the SPI readout, so it happily
    recommended a 340-sample queue whose 15.4 ms listening window cannot fit a
    13 ms beat.
    """
    fop, smclk = 176500.0, 128           # ODR 4
    for n, expect_ms in [(155, 7.02), (301, 13.64)]:
        rx_ms = n * smclk / (16.0 * fop) * 1000.0
        assert rx_ms == pytest.approx(expect_ms, abs=0.05)
    # 301 samples cannot live in a 13 ms beat, which is the upstream default
    assert 301 * smclk / (16.0 * fop) * 1000.0 > 13.0


def test_233cm_queue_geometry():
    """The installed capture point: ODR 4, 301 samples, ~234 cm, 0.78 cm bins."""
    fop = 176500.0
    reach = prof.max_range_cm(301, fop, smclk_per_sample=128, pulse_echo=True)
    assert reach == pytest.approx(234, abs=1)
    assert reach / 301 == pytest.approx(0.777, abs=0.005)
    assert 301 <= prof.IQ_SAMPLES_MAX


def test_azimuth_from_range_difference():
    """sin(theta) = dr / baseline — the interferometer relation the demo uses.

    Only sensor POSITIONS enter it, which is why the two temple units facing
    parallel forward is correct and splaying them outward would buy nothing.
    """
    import math
    b = 0.16
    for deg in (0, 10, 30, 45):
        dr = b * math.sin(math.radians(deg))
        assert math.degrees(math.asin(dr / b)) == pytest.approx(deg, abs=1e-6)
    # one range bin of error near boresight, in degrees
    err = math.degrees(math.asin(0.0078 / b))
    assert err == pytest.approx(2.8, abs=0.2)


# --- tx-burst range offset (tx160 queue) ------------------------------------

def test_tx_smclk_shifts_axis_by_burst_bins():
    """Regression: RX starts tx_smclk after TX onset, so the axis must start
    tx_smclk/smclk_per_sample bins late — in BINS, identically for PE and PC.
    """
    fop, smclk, n = 176500.0, 128, 302
    pe = prof.range_axis_raw(2, 2, fop, n, smclk_per_sample=smclk, tx_smclk=2560)
    pc = prof.range_axis_raw(2, 3, fop, n, smclk_per_sample=smclk, tx_smclk=2560)
    step = pe[1] - pe[0]
    assert step == pytest.approx(0.777, abs=0.005)
    assert pe[0] == pytest.approx(16.32, abs=0.05)   # (1 + 2560/128) * step
    assert pe[0] / step == pytest.approx(21.0)       # 20 bins offset + bin 1
    assert np.allclose(pc, 2 * pe)                   # same bins, doubled cm


def test_tx_smclk_zero_reproduces_the_old_axis_exactly():
    """tx_smclk=0 (old 16-cycle recordings) must be bit-identical to before."""
    fop, smclk, n = 176500.0, 128, 302
    step = SOUND_CM_S * smclk / (16.0 * fop) / 2.0   # PE
    old = np.arange(1, n + 1, dtype=np.float64) * step
    got = prof.range_axis_raw(2, 2, fop, n, smclk_per_sample=smclk, tx_smclk=0)
    assert np.array_equal(got, old)


def test_load_surfaces_tx_smclk_from_npz(tmp_path):
    """Regression: load() dropped tx_smclk, so every tx160 axis was ~16 cm early."""
    from echoears.session import load
    base = dict(
        iq=np.zeros((2, 1, 4), dtype=np.complex64),
        ts_us=np.array([[0], [39_000]], dtype=np.int64),
        channels=np.array([[2, 2]], dtype=np.int64),
        rx_ids=np.array([2], dtype=np.int64),
        fop_hz=np.array([176500.0]),
    )
    np.savez(tmp_path / "new.npz", tx_smclk=np.array(2560), **base)
    np.savez(tmp_path / "old.npz", **base)
    assert load(tmp_path / "new.npz").meta["tx_smclk"] == 2560
    assert "tx_smclk" not in load(tmp_path / "old.npz").meta  # old files: absent, not 0


def test_export_ears_maps_temples_to_pe_channels():
    """Left/right must resolve by sensor ID, and be None when an ID is absent."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "export_web", Path(__file__).resolve().parents[1] / "tools" / "export_web.py")
    ew = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ew)
    chans = [[2, 2], [2, 3], [3, 2], [3, 3]]
    assert ew.ears_channels(chans, left_sensor=3, right_sensor=2) == [3, 0]
    assert ew.ears_channels(chans, left_sensor=2, right_sensor=3) == [0, 3]
    assert ew.ears_channels(chans, left_sensor=5, right_sensor=2) is None


def test_live_default_beat_is_26ms_and_lands_in_the_config(monkeypatch):
    """Regression: a bare LiveSource() inherited upstream's 13 ms beat, which
    the tx160 queue's 13.7 ms listening window cannot fit — frames desynced
    instead of erroring. The safe 26 ms must be the default AND actually be
    written into the config the Rig receives.
    """
    calls = {"open": 0, "recover": 0, "close": 0}
    srcmod = _fake_stack(monkeypatch, _rig_factory(calls, succeed_on=1),
                         lambda _p: True)
    assert srcmod.LiveSource.DEFAULT_ODR_MS == 26
    src = srcmod.LiveSource("cfg", "/dev/fake")      # odr_ms left at None
    assert src.odr_ms == 26
    src.start()
    assert src.rig.config.odr_ms == 26               # replace() really applied


# --- per-bin noise normalisation (sigma units) ------------------------------

def test_noise_scale_recovers_a_known_sigma():
    """MAD-based scale must land near the true sigma of synthetic noise."""
    rng = np.random.default_rng(0)
    true = np.array([2.0, 20.0, 200.0])
    resid = rng.normal(0.0, true, size=(4000, 3))
    got = prof.noise_scale(resid)
    assert np.allclose(got, true, rtol=0.08), got


def test_noise_scale_handles_dead_and_sub_quantum_bins():
    # a bin with no variance at all is uninformative -> infinite scale -> mute
    dead = np.zeros((50, 4))
    assert np.all(np.isinf(prof.noise_scale(dead)))
    out = prof.to_sigma(dead)
    assert np.all(np.isfinite(out)) and np.all(out == 0)
    # a bin with variance below the ADC quantum is floored, not amplified
    tiny = np.zeros((400, 1))
    tiny[::2] = 0.2                      # sigma ~0.1 counts, sub-quantum
    assert prof.noise_scale(tiny)[0] == prof.NOISE_FLOOR


def test_to_sigma_is_scale_free_across_range():
    """THE point of the change: two bins with wildly different absolute
    levels but the same significance must come out equal."""
    rng = np.random.default_rng(1)
    n = 3000
    near = rng.normal(5000.0, 100.0, n)      # loud bin, sigma 100 counts
    far = rng.normal(20.0, 3.0, n)           # quiet bin, sigma 3 counts
    near[10] += 500.0                        # +5 sigma event
    far[10] += 15.0                          # +5 sigma event
    out = prof.to_sigma(np.stack([near, far], axis=1))
    assert abs(out[10, 0] - 5.0) < 0.5, out[10, 0]
    assert abs(out[10, 1] - 5.0) < 0.5, out[10, 1]


def test_to_sigma_clips_negatives_and_keeps_static_scenes_quiet():
    rng = np.random.default_rng(2)
    static = rng.normal(300.0, 3.0, size=(2000, 8))
    out = prof.to_sigma(static)
    assert out.min() >= 0.0
    # gaussian one-sided tail at 3 sigma is 0.135%; allow 3x for MAD sampling
    # error at this n, not the 15x that let a 31% scale error pass
    assert (out > 3.0).mean() < 0.004, (out > 3.0).mean()


def test_running_baseline_sigma_matches_offline_units():
    """Live and replay must mean the same thing by 'gate = 3 sigma'."""
    rng = np.random.default_rng(3)
    frames = rng.normal(1000.0, 25.0, size=(4000, 6))
    offline = prof.to_sigma(frames)
    rb = prof.RunningBaseline(alpha=0.02, sigma=True)
    online = np.stack([rb(f) for f in frames])[1000:]     # let the EMA settle
    # 10% of a ~1.6 sigma p95: a live/replay unit mismatch is the failure
    # this test is named for, so it must not tolerate 30%
    ref = np.percentile(offline, 95)
    assert abs(np.percentile(online, 95) - ref) < 0.1 * ref
    assert np.all(np.isfinite(online))


def test_counts_path_warm_up_is_bias_corrected_too():
    """The bias correction applies to the counts path (apps/live.py) as well,
    so pin the sequence at the alpha it actually runs at. alpha=0.5 would
    hide this entirely: max(0.5, 1/n) == 0.5 for every n >= 2."""
    frames = np.array([[10.0, 10.0], [12.0, 8.0], [11.0, 9.0], [13.0, 7.0]])
    rb = prof.RunningBaseline(alpha=0.02)
    out = [rb(f) for f in frames]
    assert np.array_equal(out[0], np.zeros(2))
    assert np.array_equal(out[1], np.array([2.0, 0.0]))    # clipped at 0
    # frame 2: baseline is the running mean of frames 0-1 = [11, 9], so the
    # residue is 0 — under the old crawling EMA it was 0.96
    assert np.allclose(out[2], [0.0, 0.0]), out[2]
    assert np.allclose(out[3], [2.0, 0.0]), out[3]


def test_export_sigma_codes_round_trip_within_half_a_step():
    ew = _load_module("export_web", REPO / "tools" / "export_web.py")
    sigma = np.array([[[0.0, 0.1, 3.0, 7.5, 31.9, 40.0]]])
    codes = ew.encode(sigma)
    back = codes.astype(float) * ew.SIGMA_PER_CODE
    assert codes.dtype == np.uint8
    assert np.all(np.abs(back[0, 0, :5] - sigma[0, 0, :5]) <= ew.SIGMA_PER_CODE / 2)
    assert back[0, 0, 5] == 255 * ew.SIGMA_PER_CODE        # 40 sigma clips


def test_a_variance_free_bin_mutes_instead_of_screaming():
    """Regression: a pinned bin (MAD == 0) used to be floored to the most
    sensitive possible scale, so its instrument wobble read as the loudest
    thing in the file (37.6 sigma on ch3 at 17.9 cm in scene233)."""
    n = 400
    pinned = np.full(n, 2868.0)
    pinned[7] += 37.0                       # instrument wobble, not an echo
    live = np.random.default_rng(4).normal(300.0, 5.0, n)
    out = prof.to_sigma(np.stack([pinned, live], axis=1))
    assert out[7, 0] == 0.0, out[7, 0]
    assert np.all(np.isfinite(out))
    assert prof.noise_scale(np.stack([pinned], axis=1))[0] == np.inf


def test_streaming_scale_does_not_blast_on_the_first_frames():
    """Regression: the scale EMA used to start at the noise floor and take
    ~10 s to reach the real sigma, so the first seconds of every live
    connect reported the whole axis as saturated targets."""
    rng = np.random.default_rng(5)
    frames = rng.normal(1000.0, 25.0, size=(200, 64))
    rb = prof.RunningBaseline(alpha=0.02, sigma=True)
    out = np.stack([rb(f) for f in frames])
    first_second = out[1:20]                 # ~1 s at 19.2 Hz, skip the seed
    # the bar is the steady-state distribution, not merely "below full scale":
    # removing the bias correction takes this max from ~3.4 to ~84
    assert first_second.max() < 6.0, first_second.max()
    assert np.percentile(first_second, 95) < 2.5, np.percentile(first_second, 95)


@pytest.mark.parametrize("arrive", [3, 8, 50, 150, 200, 250, 350])
def test_streaming_scale_is_not_inflated_by_the_target_it_measures(arrive):
    """A strong echo must not be allowed into its own denominator, at ANY
    arrival time — a fixed arrival frame pins the warm-up constant instead
    of the behaviour, and the first version of this test sat exactly on the
    boundary where censoring switched on."""
    rng = np.random.default_rng(6)
    frames = rng.normal(500.0, 10.0, size=(600, 4))
    frames[arrive:, 1] += 120.0              # a 12-sigma target arrives
    rb = prof.RunningBaseline(alpha=0.02, sigma=True)
    np.stack([rb(f) for f in frames])
    assert rb.scale[1] < 2.0 * rb.scale[0], (arrive, rb.scale[1], rb.scale[0])


@pytest.mark.parametrize("arrive", [50, 150, 350])
def test_a_target_arriving_after_warm_up_is_loud(arrive):
    rng = np.random.default_rng(6)
    frames = rng.normal(500.0, 10.0, size=(600, 4))
    frames[arrive:, 1] += 120.0
    rb = prof.RunningBaseline(alpha=0.02, sigma=True)
    out = np.stack([rb(f) for f in frames])
    assert out[arrive + 1, 1] > 5.0


def test_a_target_already_present_at_connect_is_absorbed_as_background():
    """A documented limitation, not a bug: background subtraction cannot
    distinguish "always been there" from "part of the room". Whatever is in
    front of the sensor when the stream opens becomes the baseline, so the
    live path only ever reports CHANGE. Pinned here so nobody re-derives it
    as a mystery on defence day."""
    rng = np.random.default_rng(7)
    frames = rng.normal(500.0, 10.0, size=(400, 4))
    frames[:, 1] += 120.0                    # present from the very first frame
    rb = prof.RunningBaseline(alpha=0.02, sigma=True)
    out = np.stack([rb(f) for f in frames])
    assert out[50:, 1].max() < 5.0, out[50:, 1].max()
    # and it becomes loud again the moment it LEAVES
    frames[300:, 1] -= 120.0
    rb2 = prof.RunningBaseline(alpha=0.02, sigma=True)
    out2 = np.stack([rb2(f) for f in frames])
    assert np.abs(out2[301:320, 1]).max() >= 0.0   # departure is a change too


# --- SIGTERM must unwind, or the board is left streaming --------------------

def _run_until_signalled(body, sig, wait=0.3, second_sig=None, tmp_path=None):
    """Run `body` in a real subprocess, signal it once it SAYS it is ready,
    return (rc, stdout).

    Readiness is the child\'s own first print ("STREAMING"/"FLASH-BEGIN"),
    not a guessed sleep: the child imports numpy before the handler is
    armed, and on a cold CI runner that takes longer than any constant —
    a fixed 1.2 s passed on every warm machine and lost the race on
    GitHub\'s ubuntu runner, where the default handler then killed the
    child before cleanup existed. `wait` is now the settle time AFTER the
    ready line, so the body is inside its loop when the signal lands."""
    import subprocess
    import tempfile
    import threading
    # plain concatenation: dedent() would be defeated by `body` having no
    # indentation of its own, leaving the prelude indented
    src = (
        "import sys, time\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "from echoears.sources import close_cleanly_on_sigterm\n"
        "close_cleanly_on_sigterm()\n"
        + body
    )
    d = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp())
    f = d / "victim.py"
    f.write_text(src)
    p = subprocess.Popen([sys.executable, str(f)], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines = []
    ready = threading.Event()

    def _pump():
        for ln in p.stdout:
            lines.append(ln)
            if "STREAMING" in ln or "FLASH-BEGIN" in ln:
                ready.set()
        ready.set()             # EOF: unblock the waiter, whatever happened

    reader = threading.Thread(target=_pump, daemon=True)
    reader.start()
    try:
        ready.wait(30)
        time.sleep(wait)
        if p.poll() is None:
            p.send_signal(sig)
        if second_sig is not None:
            time.sleep(0.3)
            if p.poll() is None:
                p.send_signal(second_sig)
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            # wait() does NOT kill on timeout; without this a regression
            # leaves a 30 s sleeper orphaned past the test
            p.kill()
            p.wait(timeout=5)
        reader.join(timeout=5)
        return p.returncode, "".join(lines)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)


BRINGUP_BODY = """
class Rig:
    def open(self):
        print("FLASH-BEGIN", flush=True)
        time.sleep(30)          # the 10-30 s programming window
        return self
    def close(self): print("RIG-CLOSE", flush=True)

rig = None
try:
    rig = Rig()
    rig.open()
except BaseException:
    if rig is not None: rig.close()
    print("CLEANED", flush=True)
    raise
"""

STREAM_BODY = """
class Rig:
    def __enter__(self): print("STREAMING", flush=True); return self
    def __exit__(self, *e): print("RIG-CLOSE", flush=True); return False
try:
    with Rig():
        while True: time.sleep(0.05)
except KeyboardInterrupt:
    print("CLEANED", flush=True)
"""


@pytest.mark.parametrize("body,label", [(STREAM_BODY, "streaming"),
                                        (BRINGUP_BODY, "bring-up")])
def test_sigterm_reaches_cleanup_in_a_real_process(body, label, tmp_path):
    """The A/B that matters, as a test rather than a commit-message claim.

    The bring-up case is the one the first cut missed: `except Exception` in
    LiveSource.start() does not catch KeyboardInterrupt, and Python skips
    __exit__ when __enter__ raises — so the 10-30 s flash, the longest
    window in the program and the one users are told to wait through, got no
    cleanup at all."""
    import signal
    rc, out = _run_until_signalled(body, signal.SIGTERM, tmp_path=tmp_path)
    assert "RIG-CLOSE" in out, (label, rc, out)
    assert "CLEANED" in out, (label, rc, out)


def test_a_second_sigterm_does_not_abort_the_cleanup_the_first_started(tmp_path):
    """Cleanup takes seconds (stop write, settle, probe, maybe a power
    cycle). A second signal landing inside it leaves the rig mid-stream —
    the exact state this mechanism exists to prevent."""
    import signal
    body = """
class Rig:
    def __enter__(self): print("STREAMING", flush=True); return self
    def __exit__(self, *e):
        print("CLOSE-BEGIN", flush=True)
        time.sleep(1.5)                 # a realistic close
        print("RIG-CLOSE", flush=True)
        return False
try:
    with Rig():
        while True: time.sleep(0.05)
except KeyboardInterrupt:
    print("CLEANED", flush=True)
"""
    rc, out = _run_until_signalled(body, signal.SIGTERM,
                                   second_sig=signal.SIGTERM, tmp_path=tmp_path)
    assert "CLOSE-BEGIN" in out, out
    assert "RIG-CLOSE" in out, out       # the second signal must not cut in


@pytest.mark.parametrize("first,second,label", [
    ("SIGINT", "SIGTERM", "launcher Ctrl-C: group SIGINT then the launcher's TERM"),
    ("SIGINT", "SIGINT", "two impatient Ctrl-Cs, no launcher"),
    ("SIGTERM", "SIGTERM", "two TERMs"),
])
def test_a_second_stop_signal_never_aborts_a_running_cleanup(first, second,
                                                             label, tmp_path):
    """Disarming only the signal that arrived left two live routes into the
    cleanup it was meant to protect. Both reproduced before the fix:
    began=True, completed=False."""
    import signal
    body = """
class Rig:
    def __enter__(self): print("STREAMING", flush=True); return self
    def __exit__(self, *e):
        print("CLOSE-BEGIN", flush=True)
        time.sleep(2.0)                 # a realistic board close
        print("CLOSE-DONE", flush=True)
        return False
try:
    with Rig():
        while True: time.sleep(0.05)
except KeyboardInterrupt:
    print("CLEANED", flush=True)
"""
    rc, out = _run_until_signalled(
        body, getattr(signal, first), second_sig=getattr(signal, second),
        wait=1.0, tmp_path=tmp_path)
    assert "CLOSE-BEGIN" in out, (label, out)
    assert "CLOSE-DONE" in out, (label, out)


def test_nohup_style_ignored_sighup_is_not_stomped():
    """`nohup` sets SIGHUP to SIG_IGN on purpose. Overriding it would make a
    nohup'd bridge die on terminal close — the opposite of the request."""
    import signal
    from echoears.sources import close_cleanly_on_sigterm

    if not hasattr(signal, "SIGHUP"):
        pytest.skip("no SIGHUP on this platform")
    saved = {s: signal.getsignal(s) for s in
             (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        close_cleanly_on_sigterm()
        assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
    finally:
        for s, h in saved.items():
            signal.signal(s, h)


@pytest.mark.skipif(not hasattr(__import__("signal"), "SIGHUP"),
                    reason="preexec_fn is POSIX-only")
def test_inherited_sigint_ignore_is_restored(tmp_path):
    """A background-launched process inherits SIGINT = SIG_IGN, so the
    bridge's own "Ctrl-C to stop" banner is false there and the rig is held
    until something sends TERM. Verified in a real subprocess started the
    way a shell backgrounds one."""
    import signal
    import subprocess
    import tempfile
    src = (
        "import signal, sys\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "print('before', signal.getsignal(signal.SIGINT) == signal.SIG_IGN, flush=True)\n"
        "from echoears.sources import close_cleanly_on_sigterm\n"
        "close_cleanly_on_sigterm()\n"
        "print('after', signal.getsignal(signal.SIGINT) == signal.SIG_IGN, flush=True)\n"
    )
    d = tmp_path
    f = d / "bg.py"
    f.write_text(src)
    # preexec_fn ignoring SIGINT reproduces exactly what `cmd &` inherits
    out = subprocess.run(
        [sys.executable, str(f)], capture_output=True, text=True, timeout=30,
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN),
    ).stdout
    assert "before True" in out, out       # the inherited state we care about
    assert "after False" in out, out       # armed, so Ctrl-C works


def test_a_deliberate_sigint_handler_is_not_stomped():
    from echoears.sources import close_cleanly_on_sigterm
    import signal

    if not hasattr(signal, "SIGHUP"):
        pytest.skip("this test saves/restores SIGHUP")

    def mine(signum, frame):              # noqa: ARG001
        pass

    saved = {s: signal.getsignal(s) for s in
             (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        signal.signal(signal.SIGINT, mine)
        close_cleanly_on_sigterm()
        assert signal.getsignal(signal.SIGINT) is mine
    finally:
        for s, h in saved.items():
            signal.signal(s, h)


def test_arming_survives_a_platform_without_sighup():
    """Windows has no SIGHUP, and the EVK ships natively for Windows. The
    first cut built the tuple outside the try, so the AttributeError escaped
    and crashed the bridge at startup on exactly that platform."""
    import signal
    import types
    from echoears import sources as srcmod

    fake = types.SimpleNamespace(
        SIGTERM=signal.SIGTERM, SIGINT=signal.SIGINT, SIG_IGN=signal.SIG_IGN,
        default_int_handler=signal.default_int_handler,
        getsignal=lambda s: None,
        signal=lambda s, h: None)       # no SIGHUP attribute at all
    real = sys.modules.get("signal")
    sys.modules["signal"] = fake
    try:
        srcmod.close_cleanly_on_sigterm()      # must not raise
    finally:
        sys.modules["signal"] = real


def test_sigterm_handler_raises_so_context_managers_run():
    """The wedge-then-replug cycle's root cause: SIGTERM's default handler
    terminates the process outright, so `with LiveSource(...)` never gets to
    stop the measurement and the NEXT open finds the rig mid-stream. Ctrl-C
    (KeyboardInterrupt) always unwound correctly — anything killing the
    process from outside did not."""
    import signal
    from echoears.sources import close_cleanly_on_sigterm

    saved = {s: signal.getsignal(s) for s in
             (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        close_cleanly_on_sigterm()
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler), handler
        assert handler is not signal.SIG_DFL
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
        # and it disarms EVERY stop signal on the way out, so a second one
        # cannot land inside the cleanup the first started
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            assert signal.getsignal(s) == signal.SIG_IGN, s
        # idempotent: arming twice must not stack or throw
        close_cleanly_on_sigterm()
    finally:
        for s, h in saved.items():
            signal.signal(s, h)


def test_full_scale_below_gate_is_refused_not_silently_binary():
    """span = max(full_scale - gate, 1e-9) turned every above-gate bin into
    full volume — a binary blast with no limiter behind it on the live path."""
    mag = np.zeros((4, 16))
    with pytest.raises(ValueError, match="must exceed gate"):
        son.sonify(mag, frame_hz=20.0, full_scale=2.0, gate=3.5)
    g = son.GrainSynth(full_scale=2.0, gate=3.5)
    with pytest.raises(ValueError, match="must exceed gate"):
        g.render(np.zeros(16), 128)


def test_write_wav_can_preserve_an_absolute_scale(tmp_path):
    """Renormalising per file undid the sigma work: the EMPTY control came
    out 1.1 dB louder than the desk scene because its lower peak was boosted
    to 0.89."""
    quiet = (np.linspace(0, 0.2, 200)).astype(np.float32)
    loud = (np.linspace(0, 0.9, 200)).astype(np.float32)
    d = tmp_path
    a = son.write_wav(d / "q.wav", quiet, peak=None)
    b = son.write_wav(d / "l.wav", loud, peak=None)

    def peak_of(path):
        with wave.open(str(path)) as w:
            return np.abs(np.frombuffer(w.readframes(w.getnframes()),
                                        dtype=np.int16) / 32768).max()

    assert peak_of(a) < 0.25 and peak_of(b) > 0.85     # scale preserved
    c = son.write_wav(d / "q2.wav", quiet)             # default still rescales
    assert peak_of(c) == pytest.approx(0.89, abs=0.01)


def test_scale_confidence_decays_to_nothing_once_the_ema_converges():
    """A permanent inflation is statistically defensible but silently
    recalibrates the gate: measured, a constant 3/sqrt(n) moved the 3.5 sigma
    false-alarm rate from 0.107% to 0.024%, a stricter detector than the one
    whose threshold came from the measured curve."""
    rng = np.random.default_rng(11)
    frames = rng.normal(800.0, 20.0, size=(3000, 8))
    warm = prof.RunningBaseline(alpha=0.02, sigma=True)
    out = np.stack([warm(f) for f in frames])

    early = out[30:80]                       # inflation still active
    late = out[2000:]                        # EMA converged, inflation gone
    assert np.percentile(early, 95) < np.percentile(late, 95), (
        np.percentile(early, 95), np.percentile(late, 95))
    # and the settled level must be the honest ~1.6-1.9 sigma, not depressed
    assert 1.4 < np.percentile(late, 95) < 2.1, np.percentile(late, 95)


def test_streaming_output_is_silent_while_the_scale_is_seeded():
    rng = np.random.default_rng(12)
    frames = rng.normal(500.0, 15.0, size=(60, 4))
    rb = prof.RunningBaseline(alpha=0.02, sigma=True)
    out = np.stack([rb(f) for f in frames])
    assert np.all(out[:prof.SCALE_SEED_FRAMES] == 0.0)
    assert out[prof.SCALE_SEED_FRAMES + 5:].max() > 0.0


def test_warm_up_inflation_does_not_deafen_the_first_seconds():
    """The inflation is a two-sided trade: it raises the effective gate while
    it is active. Pin both ends so a change to the form cannot silently
    deafen the warm-up (or silently stop protecting it)."""
    warm = 1.0 / 0.005

    def eff_gate(n, gate=3.5):
        e = max(n - 1, 1)
        return gate * (1.0 + prof.SCALE_CONFIDENCE
                       * max(0.0, 1 / np.sqrt(e) - 1 / np.sqrt(warm)))

    first = eff_gate(prof.SCALE_SEED_FRAMES + 1)
    assert 4.0 < first < 6.0, first          # raised, but not deafening
    assert eff_gate(200) == pytest.approx(3.5, abs=0.02)   # gone by ~10 s
    assert eff_gate(5000) == pytest.approx(3.5, abs=1e-6)  # and stays gone


def test_streaming_mutes_the_same_dead_bins_as_the_offline_path():
    """A variance-free bin is uninformative in both paths. The streaming
    path used to floor it at NOISE_FLOOR instead of muting it, reading up to
    6.95 sigma on real data — nearly twice the gate — on exactly the bins the
    offline path silences."""
    n = 400
    pinned = np.full(n, 2868.0)
    pinned[300] += 37.0                      # instrument wobble, not an echo
    live = np.random.default_rng(13).normal(300.0, 5.0, n)
    frames = np.stack([pinned, live], axis=1)

    assert np.isinf(prof.noise_scale(frames - np.median(frames, axis=0))[0])
    rb = prof.RunningBaseline(alpha=0.02, sigma=True)
    out = np.stack([rb(f) for f in frames])
    assert out[300, 0] == 0.0, out[300, 0]   # the wobble does not un-mute it
    assert np.all(np.isfinite(out))
    # judging AFTER the update would let the wobble un-mute its own bin,
    # which is how this read 37 sigma before the fix
    assert out[:, 0].max() == 0.0, out[:, 0].max()


# --- hardware-rule target detection -----------------------------------------

def test_threshold_curve_is_piecewise_constant_with_tail():
    from echoears import detect
    c = detect.threshold_curve(302)
    assert c[0] == 1200 and c[39] == 1200      # first segment
    assert c[40] == 5000 and c[44] == 5000     # ringdown skirt
    assert c[219] == 125 and c[301] == 125     # last value continues past 220


def test_detect_reports_a_static_wall_the_sigma_path_erases():
    """The point of the mode: 'what IS there', not 'what changed'. A still
    reflector above the vendor line is a target every frame."""
    from echoears import detect
    rng = np.random.default_rng(20)
    n = 302
    frames = rng.normal(30.0, 6.0, size=(60, n))
    frames[:, :40] += 18000.0                  # ringdown, static
    frames[:, 100] += 290.0                    # the desk at ~94 cm, static
    curve = detect.threshold_curve(n)
    est = np.median(frames, axis=0)
    hits = [detect.detect_targets(f, curve, static_est=est) for f in frames]
    assert all(h and h[0][0] == 100 for h in hits), hits[0]
    # over = mag/threshold at that bin (threshold 200 there)
    assert 1.2 < hits[0][0][1] < 2.5, hits[0][0]


def test_detect_ringdown_region_uses_cancellation_not_raw():
    """The vendor curve's first segment (1200) assumes ringdown cancellation
    — raw ringdown is ~18000 and would flood it. With the static estimate
    the region is quiet; a NEW near object above the residue line is seen."""
    from echoears import detect
    rng = np.random.default_rng(21)
    n = 302
    frames = rng.normal(30.0, 6.0, size=(60, n))
    frames[:, :40] += 18000.0
    curve = detect.threshold_curve(n)
    est = np.median(frames, axis=0)
    # static scene: nothing in the ringdown zone fires
    assert not any(i < 40 for f in frames
                   for i, _ in detect.detect_targets(f, curve, static_est=est))
    # a new hand appears at bin 20 with 2000 counts over the static template
    hand = frames[0].copy()
    hand[19:22] += 2000.0
    hits = detect.detect_targets(hand, curve, static_est=est)
    assert any(i in (19, 20, 21) for i, _ in hits), hits
    # without an estimate the region is blanked, not flooded
    assert not any(i < 40 for i, _ in
                   detect.detect_targets(frames[0], curve, static_est=None))


def test_detect_caps_at_five_targets_strongest_first():
    from echoears import detect
    n = 302
    frame = np.full(n, 10.0)
    for k, bin_ in enumerate([60, 90, 120, 150, 180, 210, 240]):
        frame[bin_] = 3000.0 - 100 * k         # 7 peaks, descending
    curve = detect.threshold_curve(n)
    hits = detect.detect_targets(frame, curve, static_est=np.zeros(n))
    assert len(hits) == detect.MAX_TARGETS == 5
    overs = [o for _, o in hits]
    assert overs == sorted(overs, reverse=True)
