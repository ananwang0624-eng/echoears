"""tools/record.capture round-trip — no hardware, fake source."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echoears.session import load  # noqa: E402
from tools.record import capture  # noqa: E402


class FakeSrc:
    """Just enough of LiveSource's surface for capture()."""
    channels = [(2, 2), (2, 3), (3, 2), (3, 3)]
    rx_ids = [2, 3]
    fop_hz = [176000.0, 176500.0]
    odr_ms = 52

    def __init__(self):
        self.i = 0

    def poll(self):
        self.i += 1
        mag = np.full((4, 302), float(self.i), dtype=np.float32)
        return [(self.i * 52000, mag)]


def test_capture_roundtrip(tmp_path):
    out = tmp_path / "hand233.npz"
    entry = capture(FakeSrc(), 0.2, "hand", "单手推拉", out)

    assert entry["label"] == "hand"
    assert entry["frames"] >= 2
    assert Path(entry["file"]) == out and out.is_file()

    sess = load(out)
    assert sess.iq.shape[1:] == (4, 302)
    assert sess.iq.shape[0] == entry["frames"]
    # the backlog frame from before recording started must be dropped:
    # FakeSrc's first poll returns magnitude 1.0, which capture() discards
    assert np.abs(sess.iq[0]).max() >= 2.0
    assert [tuple(c) for c in sess.channels] == FakeSrc.channels

    raw = np.load(out)
    assert int(raw["odr_ms"]) == 52          # taken from the source, not a default
    assert str(raw["label"]) == "hand"


def test_rangefinder_cfg_parse(tmp_path):
    from echoears.rangefinder import PRESETS, cfg_cic_odr
    assert set(PRESETS) == {"long", "short", "static", "default"}
    p = tmp_path / "x.json"
    p.write_text('{"meas": [{"odr": 6}, {"odr": 6}]}')
    assert cfg_cic_odr(p) == 6
