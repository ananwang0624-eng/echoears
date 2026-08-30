"""Distance profiles -> audible sound.

The mapping, deliberately kept to one idea:

    time within a grain  =  distance
    grain amplitude      =  echo strength
    grain rate           =  sensor frame rate

Each frame's range profile is stretched into a short "scan sweep": an echo at
5 cm sounds early in the grain, one at 20 cm sounds late. Played back at the
capture frame rate the result runs in real time, so a hand moving toward the
sensor is heard as the bright part of the sweep marching earlier.

Pitch optionally tracks distance as well (near = high). That is redundant with
the timing cue on purpose — redundant coding is easier to learn than either cue
alone.

Carrier phase is integrated over the whole signal rather than per grain, so
grain boundaries introduce no discontinuity and therefore no clicks.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def _stretch(profile: np.ndarray, out_len: int) -> np.ndarray:
    """Linear-interpolate a range profile onto `out_len` points."""
    src = np.linspace(0.0, 1.0, profile.shape[0])
    dst = np.linspace(0.0, 1.0, out_len)
    return np.interp(dst, src, profile)


def sonify(
    mag: np.ndarray,
    *,
    frame_hz: float,
    sr: int = 44100,
    speed: float = 1.0,
    f_near: float = 1800.0,
    f_far: float = 300.0,
    sweep: bool = True,
    gamma: float = 0.5,
    full_scale: float | None = None,
    gate: float = 0.0,
) -> np.ndarray:
    """Turn a (n_frames, n_samples) magnitude array into mono float32 audio.

    Parameters
    ----------
    frame_hz : capture frame rate; one grain is emitted per frame.
    speed    : 1.0 plays at real time; 0.25 stretches 4x (easier to hear).
    f_near / f_far : carrier frequency at the near and far end of each sweep.
    sweep    : False pins the carrier at `f_near` (timing cue only).
    gamma    : amplitude compression exponent applied to the envelope.
               0.5 = square root; echoes span a huge dynamic range and a raw
               linear envelope leaves everything but the strongest inaudible.
    full_scale : if given, normalise against THIS instead of the block peak.
               Pass it when `mag` is already in noise sigmas (profile.to_sigma)
               — then loudness is absolute and comparable between recordings,
               instead of every file being stretched to its own loudest bin.
    gate     : values below this are silence. Only meaningful with
               `full_scale`, because a threshold on raw counts means a
               different thing at every range (that is the whole point of
               sigma units).
    """
    if mag.ndim != 2:
        raise ValueError(f"mag must be (n_frames, n_samples), got {mag.shape}")
    n_frames, n_samples = mag.shape

    grain_len = max(1, int(round(sr / (frame_hz * speed))))
    total = n_frames * grain_len

    # --- envelope: distance -> time, one grain per frame -------------------
    env = np.empty(total, dtype=np.float64)
    for i in range(n_frames):
        env[i * grain_len : (i + 1) * grain_len] = _stretch(mag[i], grain_len)

    if full_scale is not None:
        if full_scale <= gate:
            raise ValueError(
                f"full_scale ({full_scale}) must exceed gate ({gate}); "
                f"otherwise every bin above the gate maps to full volume — "
                f"a binary blast into headphones with no limiter behind it")
        env = np.clip(env - gate, 0.0, None)
        span = max(full_scale - gate, 1e-9)
        env = np.clip(env / span, 0.0, 1.0) ** gamma
    else:
        peak = float(env.max()) if env.size else 0.0
        env = (env / peak) ** gamma if peak > 0 else env

    # --- carrier: continuous phase, frequency swept within each grain ------
    if sweep:
        pos = np.tile(np.linspace(0.0, 1.0, grain_len, endpoint=False), n_frames)
        freq = f_near + (f_far - f_near) * pos
    else:
        freq = np.full(total, f_near)
    phase = 2.0 * np.pi * np.cumsum(freq) / sr

    return (env * np.sin(phase)).astype(np.float32)


class GrainSynth:
    """Stateful per-frame grain synthesizer for the live path.

    Same mapping as `sonify()` (time within grain = distance, swept carrier),
    but renders one frame at a time and carries the carrier phase across calls
    so consecutive grains join without clicks. One instance per output channel.
    """

    def __init__(self, *, sr: int = 44100, f_near: float = 1800.0,
                 f_far: float = 300.0, sweep: bool = True, gamma: float = 0.5,
                 full_scale: float | None = None, gate: float = 0.0):
        self.sr = sr
        self.f_near = f_near
        self.f_far = f_far
        self.sweep = sweep
        self.gamma = gamma
        #: see sonify(); with sigma-domain input this replaces the decaying
        #: peak tracker, which existed only to tame the 70 dB spread that
        #: per-bin normalisation removes upstream
        self.full_scale = full_scale
        self.gate = gate
        self._phase = 0.0
        # Live frames have no global peak to normalize against, so track one.
        self._peak = 1e-9

    def render(self, profile: np.ndarray, n_out: int) -> np.ndarray:
        """One range profile -> `n_out` audio samples (float32)."""
        env = _stretch(np.asarray(profile, dtype=np.float64), n_out)
        if self.full_scale is not None:
            if self.full_scale <= self.gate:
                raise ValueError(
                    f"full_scale ({self.full_scale}) must exceed gate "
                    f"({self.gate}); see sonify()")
            env = np.clip(env - self.gate, 0.0, None)
            span = max(self.full_scale - self.gate, 1e-9)
            env = np.clip(env / span, 0.0, 1.0) ** self.gamma
        else:
            self._peak = max(self._peak * 0.999, float(env.max()))  # slow decay
            env = (env / self._peak) ** self.gamma if self._peak > 0 else env

        if self.sweep:
            pos = np.linspace(0.0, 1.0, n_out, endpoint=False)
            freq = self.f_near + (self.f_far - self.f_near) * pos
        else:
            freq = np.full(n_out, self.f_near)
        phase = self._phase + 2.0 * np.pi * np.cumsum(freq) / self.sr
        self._phase = float(phase[-1]) % (2.0 * np.pi)
        return (env * np.sin(phase)).astype(np.float32)


def write_wav(path: str | Path, audio: np.ndarray, sr: int = 44100,
              peak: float | None = 0.89) -> Path:
    """Write mono (n,) or stereo (n, 2) float audio as 16-bit PCM.

    `peak=None` writes the samples as they are (clipped to +-1). Pass it
    whenever the synth used `full_scale`, or this renormalisation undoes the
    absolute scale: measured on the shipped captures, the EMPTY control came
    out 1.1 dB LOUDER than the desk scene, because its quietest-file peak
    got a x1.52 boost to reach 0.89. That is the per-file auto-gain the
    sigma work exists to remove, reintroduced at file granularity.
    """
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.ndim != 2 or audio.shape[1] not in (1, 2):
        raise ValueError(f"audio must be (n,) or (n, 1|2), got {audio.shape}")

    if peak is None:
        audio = np.clip(audio, -1.0, 1.0)
        m = 0.0                       # skip the rescale below
    else:
        m = float(np.max(np.abs(audio))) if audio.size else 0.0
    if m > 0:
        audio = audio * (peak / m)
    pcm = np.clip(audio * 32767.0, -32768, 32767).astype("<i2")

    path = Path(path)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(audio.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path
