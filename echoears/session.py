"""Standalone reader for the ultrasonic matrix npz schema (v1).

Deliberately does NOT import the `ultrasonic` repo: this package must stay
runnable on its own, including on a machine with no EVK install. The schema is
small and stable, so a ~60-line reader is cheaper than a cross-repo dependency.

Schema v1 (verified against real files 2026-08-28):
    iq          complex64 (n_frames, n_channels, n_samples)   assembled frames
    ts_us       int64     (n_frames, n_tx)                    per-beat timestamps
    channels    int64     (n_channels, 2)                     (tx_id, rx_id) rows
    rx_ids      int64     (n_rx,)
    fop_hz      float64   (n_rx,)                             PMUT operating freq
    raw_ts/raw_rx/raw_iq                                      pre-assembly stream
    scalar 0-d arrays: schema, label, subject, note, config, config_json,
                       odr_ms, n_bad, cal_iters, fw, created, assembler_version

Note the metadata are SEPARATE 0-d arrays, not one packed `meta` key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SOUND_CM_S = 34300.0  # speed of sound, cm/s


def _scalar(z, key, default=None):
    """Read a 0-d array out of an npz as a plain Python value."""
    if key not in z.files:
        return default
    v = z[key]
    return v.item() if v.ndim == 0 else v


@dataclass
class Session:
    """One recording. `iq` is (n_frames, n_channels, n_samples) complex64."""

    iq: np.ndarray
    ts_us: np.ndarray
    channels: np.ndarray  # (n_channels, 2) rows of (tx_id, rx_id)
    rx_ids: np.ndarray
    fop_hz: np.ndarray
    meta: dict = field(default_factory=dict)
    path: Path | None = None

    # ---- shape helpers ---------------------------------------------------
    @property
    def n_frames(self) -> int:
        return int(self.iq.shape[0])

    @property
    def n_channels(self) -> int:
        return int(self.iq.shape[1])

    @property
    def n_samples(self) -> int:
        return int(self.iq.shape[2])

    @property
    def label(self) -> str:
        return self.meta.get("label", "?")

    @property
    def frame_hz(self) -> float:
        """Measured frame rate from the timestamps (not the configured one)."""
        t = self.ts_us[:, 0]
        span_s = (t[-1] - t[0]) / 1e6
        return (len(t) - 1) / span_s if span_s > 0 else 0.0

    def is_pulse_echo(self, ch: int) -> bool:
        tx, rx = self.channels[ch]
        return int(tx) == int(rx)

    def describe(self) -> str:
        m = self.meta
        return "\n".join(
            [
                f"path      {self.path}",
                f"label     {self.label}   subject {m.get('subject','?')}",
                f"note      {m.get('note','')!r}",
                f"frames    {self.n_frames} x {self.n_channels}ch x {self.n_samples}s",
                f"rate      {self.frame_hz:.2f} Hz measured "
                f"(odr_ms={m.get('odr_ms','?')})   dur {self.duration_s:.1f} s",
                f"rx_ids    {list(self.rx_ids)}   fop {np.round(self.fop_hz).astype(int).tolist()}",
                f"channels  {[tuple(int(v) for v in c) for c in self.channels]}",
                f"config    {m.get('config','?')}   schema v{m.get('schema','?')}"
                f"   fw {m.get('fw','?')}   created {m.get('created','?')}",
            ]
        )

    @property
    def duration_s(self) -> float:
        t = self.ts_us[:, 0]
        return float((t[-1] - t[0]) / 1e6) if len(t) > 1 else 0.0


def load(path: str | Path) -> Session:
    """Load a schema-v1 npz. Raises on a file that is not one."""
    path = Path(path)
    z = np.load(path, allow_pickle=False)
    missing = {"iq", "ts_us", "channels", "rx_ids", "fop_hz"} - set(z.files)
    if missing:
        raise ValueError(f"{path.name}: not a matrix session npz (missing {sorted(missing)})")

    meta = {}
    for k in (
        "schema", "assembler_version", "config", "config_json", "label",
        "subject", "note", "n_bad", "cal_iters", "odr_ms", "fw", "created",
        "tx_smclk",  # written by tools/record.py; shifts the range axis
    ):
        v = _scalar(z, k)
        if v is not None:
            meta[k] = v
    if "config_json" in meta:
        try:
            meta["config"] = json.loads(meta["config_json"])
        except (json.JSONDecodeError, TypeError):
            pass  # keep the raw string

    return Session(
        iq=z["iq"],
        ts_us=z["ts_us"],
        channels=z["channels"],
        rx_ids=z["rx_ids"],
        fop_hz=z["fop_hz"],
        meta=meta,
        path=path,
    )
