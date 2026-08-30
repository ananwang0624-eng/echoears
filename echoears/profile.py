"""IQ frames -> distance profiles.

The range axis is the one thing in this stack that is easy to get silently
wrong, so this module makes it explicit and refuses to guess.

WHAT SETS WHAT
--------------
    range   <- total RX instruction length, in SMCLK cycles
               (how long the sensor listens; nothing else changes it)
    samples  = rx_smclk / smclk_per_sample
    resolution (cm/sample) <- smclk_per_sample, i.e. the CIC ODR

So ODR does NOT set the range. It sets how finely the listening window is
sliced. Its practical role is that the IQ buffer holds at most
IQ_SAMPLES_MAX = 340 samples, so at a fine ODR you run out of buffer before
you run out of listening time.

`smclk_per_sample` is NOT stored in the npz (the CaptureConfig has no CIC-ODR
field), so every function here takes it explicitly. The upstream repo hardcodes
it as 32 in `matrix/frames.py`, which is correct only while the meas queue says
odr=6 — change the queue and every axis is silently mislabeled with no error.
"""

from __future__ import annotations

import numpy as np

from .session import SOUND_CM_S, Session

#: CIC ODR -> SMCLK cycles per output IQ sample.  16 * 2**(7 - odr).
#: Matches the vendor definition (`cfgwriter.ODR_TO_CYCLES`).
ODR_SMCLK_PER_SAMPLE = {2: 512, 3: 256, 4: 128, 5: 64, 6: 32}

#: Firmware IQ buffer ceiling (shasta_iq_format.h: IQ_SAMPLES_MAX).
IQ_SAMPLES_MAX = 340


def smclk_for_odr(odr: int) -> int:
    """SMCLK cycles per IQ sample for a CIC ODR code."""
    try:
        return ODR_SMCLK_PER_SAMPLE[odr]
    except KeyError:
        raise ValueError(f"odr must be one of {sorted(ODR_SMCLK_PER_SAMPLE)}, got {odr}") from None


#: TX burst of the one queue echoears captures with (txrot_long233_tx160:
#: 160 PMUT cycles = 2560 SMCLK). RX starts this long after TX onset, so an
#: echo landing in bin 0 left a target 2560/128 = 20 bins away — ~15.5 cm PE.
#: With the old 16-cycle queue the offset was 2 bins (~1.6 cm) and ignorable,
#: which is why this parameter did not exist before.
LIVE_TX_SMCLK = 2560


def range_axis_raw(tx: int, rx: int, fop_hz: float, n_samples: int,
                   *, smclk_per_sample: int, tx_smclk: int = 0) -> np.ndarray:
    """Distance axis in cm from raw channel facts (no Session needed).

    Pulse-echo channels (tx == rx) are halved: the echo travels out and back,
    so object range is half the path. Pitch-catch channels return the total
    bistatic path (tx -> target -> rx), which for a target far compared to the
    sensor spacing is also ~2x the object range.

    `tx_smclk` is the TX burst length: sample 0 is captured that long after
    TX onset, so the whole axis shifts late by tx_smclk/smclk_per_sample
    bins. The axis labels the echo ONSET; the burst itself is ~16 cm long in
    air at 160 cycles, and that smear — not the bin pitch — is the actual
    resolution.
    """
    step = SOUND_CM_S * smclk_per_sample / (16.0 * fop_hz)
    if tx == rx:
        step /= 2.0
    off = tx_smclk / smclk_per_sample
    return (np.arange(1, n_samples + 1, dtype=np.float64) + off) * step


def range_axis(sess: Session, ch: int, *, smclk_per_sample: int,
               tx_smclk: int = 0) -> np.ndarray:
    """Distance axis in cm for one channel of a Session.

    Recordings made with the tx160 queue need tx_smclk=LIVE_TX_SMCLK; older
    16-cycle recordings carry a ~1.6 cm offset and 0 stays honest enough.
    """
    tx, rx = (int(v) for v in sess.channels[ch])
    fop = float(sess.fop_hz[list(sess.rx_ids).index(rx)])
    return range_axis_raw(tx, rx, fop, sess.n_samples,
                          smclk_per_sample=smclk_per_sample, tx_smclk=tx_smclk)


def max_range_cm(n_samples: int, fop_hz: float, *, smclk_per_sample: int,
                 pulse_echo: bool = True) -> float:
    """Furthest bin, in cm. Handy for planning a meas queue."""
    step = SOUND_CM_S * smclk_per_sample / (16.0 * fop_hz)
    if pulse_echo:
        step /= 2.0
    return step * n_samples


def rx_smclk_for_range(range_cm: float, fop_hz: float, *,
                       pulse_echo: bool = True) -> int:
    """RX instruction length (SMCLK) needed to listen out to `range_cm`.

    This is the knob that actually buys range.
    """
    path_cm = range_cm * 2.0 if pulse_echo else range_cm
    seconds = path_cm / SOUND_CM_S
    return int(round(seconds * 16.0 * fop_hz))


def magnitude(sess: Session, ch: int) -> np.ndarray:
    """|IQ| for one channel -> (n_frames, n_samples) float32."""
    return np.abs(sess.iq[:, ch, :]).astype(np.float32)


def remove_static(mag: np.ndarray) -> np.ndarray:
    """Subtract the per-bin median over time (clutter / ringdown removal).

    The near bins are dominated by transducer ringdown and fixed rig echoes,
    both constant across frames. Removing the temporal median leaves what
    moved — which is what is worth listening to. Result is clipped at 0.
    """
    return np.clip(mag - np.median(mag, axis=0, keepdims=True), 0, None)


def normalize(x: np.ndarray, peak: float = 1.0) -> np.ndarray:
    """Scale so max |x| == peak. All-zero input stays all-zero (no NaN)."""
    m = float(np.max(np.abs(x))) if x.size else 0.0
    return x * (peak / m) if m > 0 else np.zeros_like(x)


#: MAD -> sigma for a normal distribution.
MAD_TO_SIGMA = 1.4826
#: E|x| -> sigma for a zero-mean normal, used by the streaming estimator
#: (a median is not streamable; a mean absolute deviation is).
MAD_MEAN_TO_SIGMA = 1.2533
#: How far above the current scale a sample is allowed to count when
#: updating that scale. The streaming analogue of the MAD's breakdown point.
CENSOR_SIGMAS = 3.0
#: How hard to widen the streaming scale while it is still built from few
#: samples — and ONLY while.
#:
#: This is a two-sided trade and both sides are measured. Widening suppresses
#: warm-up false alarms (worst-seed peak 25.5 sigma at 0, 13.5 at 3, 11.2 at
#: 5) but it also RAISES THE EFFECTIVE GATE, because the browser's 3.5 sigma
#: threshold now sits on an inflated scale: at the first emitted frame the
#: smallest audible true echo is 3.50 sigma at conf 0, 5.11 at 3, 6.18 at 5,
#: decaying to 3.50 by ~10 s. 3 is chosen because a real hand at half a metre
#: measured tens of sigma, so a 5.1 sigma floor for one second costs nothing
#: real, while a spurious 25 sigma bin is an audible click. Only the false-
#: alarm side was measured when this was first tuned; the miss side only
#: surfaced on a later audit. A permanent inflation would be defensible
#: statistically (an EMA's estimate never becomes certain) but it silently
#: recalibrates the gate: measured, a constant 3/sqrt(n) took the 3.5 sigma
#: false-alarm rate from 0.107% to 0.024%, i.e. a stricter detector than the
#: one whose threshold was chosen from the measured curve. So it decays to
#: exactly 1.0 by the time the scale EMA has converged.
SCALE_CONFIDENCE = 3.0
#: Frames before the streaming path emits anything, and before the censor
#: engages. Two jobs that were conflated, and the sweep that "picked" 20 was
#: confounded: it measured "the first second AFTER the seed", so changing the
#: constant also moved the measurement window. Re-swept over a FIXED frame
#: window, the censor start has no effect anywhere in [5, 40] — only 0
#: differs — so 20 is not tuned for that at all. What 20 buys is the output
#: silence, which is real: emitting from a scale built on a handful of
#: samples put 3 of 12 seeds over the browser's full scale. About 1 s at
#: 19.2 Hz, and the ping engine samples ~1 frame in 16, so it costs at most
#: a ping or two.
SCALE_SEED_FRAMES = 20
#: Floor for a noise scale, in ADC counts. |I+jQ| of integer I/Q has a
#: smallest nonzero value of 1, so a scale below that is sub-quantum and not
#: measurable; flooring there is the conservative direction (it can only
#: reduce reported significance).
NOISE_FLOOR = 1.0


def noise_scale(residue: np.ndarray) -> np.ndarray:
    """Per-bin noise sigma of a clutter-removed block, via the MAD.

    `residue` is (n_frames, n_samples). Median absolute deviation rather than
    std: a few frames containing a real echo would inflate a std and then
    hide themselves behind it.
    """
    r = np.asarray(residue, dtype=np.float64)
    med = np.median(r, axis=0, keepdims=True)
    sigma = MAD_TO_SIGMA * np.median(np.abs(r - med), axis=0)
    # A bin whose residue has NO measurable spread is not the most sensitive
    # bin in the file, it is an uninformative one: the CIC output there is
    # pinned (saturated ringdown, dead channel), so every wobble it does make
    # is instrument, not scene. Flooring such a bin to the smallest legal
    # scale made a 37-count wobble on a pinned 2868-count ringdown read as
    # 37.6 sigma on ch3 at 17.9 cm — the loudest thing in that recording,
    # one blind-zone bin from being audible. Mute it instead.
    return np.where(sigma <= 0.0, np.inf, np.maximum(sigma, NOISE_FLOOR))


def to_sigma(mag: np.ndarray) -> np.ndarray:
    """Clutter-removed magnitudes expressed in per-bin noise sigmas.

    THE reason this exists: raw counts span ~70 dB across the range axis
    (ringdown at 20 cm is ~2400x the level at 2 m), so any single threshold
    is meaningless — a gate tuned for the near field silences everything far,
    and one tuned far lets ringdown residue through as a phantom target.
    Dividing each bin by its own measured noise makes the output scale-free:
    "3" means three sigma above what that bin does when nothing is there, at
    16 cm and at 250 cm alike.

    Measured on the real 233 cm captures, pooling the two pulse-echo ears
    over four range bands: the 95th percentile of a static scene spreads
    57.6 dB as raw magnitudes, 33.8 dB as clutter-removed residue counts,
    and 0.94 dB in sigma units.

    A range-only TVG is NOT far behind on that metric — r^2.0 reaches
    1.80 dB — so flatness alone is not the argument. What it cannot do:
    the exponent has to be fitted (r^2.5, which matches the measured
    spreading slope, gives 6.86 dB), it amplifies the variance-free bins
    this function mutes, and it leaves the threshold in scaled counts with
    no false-alarm meaning attached. A pitch-
    catch channel is flat too except for the five bins at the very start of
    its longer bistatic axis, which sit inside the transmit overlap and read
    LOW — the safe direction.

    Detection SNR of a SYNTHETIC additive target at 25% of local clutter
    improved 2-7 dB in three of four bands (the fourth was ~1 dB worse).
    That experiment is close to circular — the injected target obeys the
    same additive model this function assumes — so it is supporting
    evidence, not proof; no recording with real motion exists yet.

    Not a full CFAR: the noise estimate is per-bin over time, not a sliding
    window over neighbouring range cells, because the clutter here is fixed
    structure (ringdown, rig echoes) rather than a moving sea surface. That
    is not a hunch — a CA-CFAR with a burst-matched 21-bin guard was built
    and lost in all 8 band/channel combinations by 1.7-3.3 dB, because its
    training ring straddles the ringdown skirt (a textbook clutter edge).

    Non-causal: the median needs the whole block. Two consequences worth
    knowing — cropping frames before calling this renormalises every value,
    and MAD's 50% breakdown means a target parked in one bin for more than
    half the capture becomes the baseline and inverts sign.
    """
    residue = np.asarray(mag, dtype=np.float64) - np.median(mag, axis=0, keepdims=True)
    return np.clip(residue / noise_scale(residue), 0, None)


class RunningBaseline:
    """Streaming clutter removal, optionally in per-bin noise sigmas.

    Keeps a per-bin exponential moving average of the magnitude as the clutter
    estimate (ringdown + fixed rig echoes) and returns the positive residue.
    An EMA is not a median, but at alpha ~0.02 it moves ~50x slower than a
    hand does at 19-40 Hz frame rates, which is what matters here.

    With `sigma=True` it also tracks a per-bin mean absolute residue and
    divides by it, so the output is in noise sigmas exactly like `to_sigma`
    — the streaming counterpart, so live and replay speak the same units and
    one gate setting means the same thing in both.

    The scale EMA is deliberately slower than the baseline EMA: a scale that
    reacts as fast as the signal would grow to swallow a real echo and
    normalise it back to ~1 sigma.
    """

    def __init__(self, alpha: float = 0.02, sigma: bool = False,
                 scale_alpha: float | None = None):
        self.alpha = float(alpha)
        self.sigma = bool(sigma)
        self.scale_alpha = float(scale_alpha if scale_alpha is not None
                                 else alpha / 4.0)
        self.baseline: np.ndarray | None = None
        self.scale: np.ndarray | None = None
        self.n = 0

    def __call__(self, mag: np.ndarray) -> np.ndarray:
        """Feed one frame (n_samples,) or (n_ch, n_samples); returns residue."""
        m = np.asarray(mag, dtype=np.float32)
        self.n += 1
        if self.baseline is None:
            self.baseline = m.copy()
            self.scale = np.zeros_like(m)
            return np.zeros_like(m)
        resid = m - self.baseline
        # Bias-corrected warm-up: for the first frames the effective rate is
        # 1/n, i.e. a running mean, so the estimators start AT the data
        # instead of crawling to it. Seeding the scale at the noise floor and
        # letting it climb over 10 s meant the first ~20 s of every live
        # connect reported the whole axis as saturated targets (measured:
        # 11.8% of bins above full scale in the first second, +16 dB).
        a = max(self.alpha, 1.0 / self.n)
        self.baseline += a * resid
        out = np.clip(resid, 0, None)
        if not self.sigma:
            return out

        # 1/(n-1): the scale receives no sample at n == 1 (that frame returns
        # early), so a 1/n weight leaves it (n-1)/n low — 4.8% at the first
        # emitted frame, partially cancelling the inflation below. The
        # baseline's 1/n at the line above IS right: it was seeded at n == 1.
        sa = max(self.scale_alpha, 1.0 / max(self.n - 1, 1))
        dev = np.abs(resid)
        was_dead = self.scale <= 0.0
        sig = np.maximum(self.scale * MAD_MEAN_TO_SIGMA, NOISE_FLOOR)
        # Censored update: a real echo is 10-40x the local noise, and letting
        # it into its own denominator is how a target normalises itself away.
        # 3 sigma is the streaming analogue of the MAD's breakdown point.
        #
        # WINSORISE, do not reject: clamping lets an outlier still move the
        # scale by a bounded amount, so a target present at connect cannot
        # inflate its own denominator and the estimator still converges.
        #
        # An earlier comment here claimed rejecting outright would DEADLOCK
        # the estimator (seed scale 0 -> everything looks too loud -> nothing
        # accepted -> stuck at 0). That was wrong, caught on re-reading NOISE_FLOOR:
        # NOISE_FLOOR floors `sig` at 1.0, so the frame-2 threshold is 3
        # counts, not 0, and the scale bootstraps. Measured on scene233 and
        # on synthetic noise, censoring from frame 1 lands within 2% of the
        # seeded result with the same single stuck bin. The symptom I
        # actually saw was a slow start, not a lock. The comment mattered
        # because someone removing NOISE_FLOOR would have been guarding
        # against a failure mode that never existed.
        dev_eff = (np.minimum(dev, CENSOR_SIGMAS * sig)
                   if self.n > SCALE_SEED_FRAMES else dev)
        self.scale = self.scale + sa * (dev_eff - self.scale)
        # Widen the scale while it is still uncertain. For a half-normal the
        # mean absolute deviation of n samples has a relative standard error
        # of sqrt(pi/2 - 1)/sqrt(n) = 0.76/sqrt(n) — the 0.76 is folded into
        # SCALE_CONFIDENCE, so this knob is a ~4-sigma bound, not 3. Anyone
        # "correcting" the form to include it would weaken the mitigation by
        # a third without noticing.
        # so a bin whose first few samples happened to be quiet gets a scale
        # that is too small and everything after it reads hot. Inflating the
        # denominator by that uncertainty is the same idea as an upper
        # confidence bound, and it decays to nothing as the estimate earns
        # its keep.
        #
        # Measured across 12 different seeds of the shipped recordings, worst
        # first-second peak after the seed: 19.5 sigma without this, 13.5
        # with. Note what that does NOT mean: bins above the browser's full
        # scale are the top of the range being used, and the settled stream
        # has them too (0.0014% steady vs 0.0041% warming). The pathology
        # this guards against is the original bug's 11.8% for twenty seconds
        # — percent, not thousandths. The earlier "0.000%" was one lucky
        # seed, which is exactly why one cold start is not a measurement.
        # Mirror noise_scale(): a bin with NO measurable spread is
        # uninformative, not maximally sensitive. The offline path gives it
        # an infinite scale and mutes it; the streaming path used to floor it
        # at NOISE_FLOOR instead and read up to 6.95 sigma there — nearly
        # twice the gate — on bins the offline path deliberately silences.
        #
        # The two cannot agree perfectly: offline uses a MEDIAN absolute
        # deviation, which a minority of wobbles cannot move, and a streaming
        # estimator has no median in O(1) memory. A bin that is pinned most
        # of the time but occasionally twitches is muted offline and is not
        # muted here. On the shipped captures every such bin lands at
        # 16.3-17.9 cm, inside the 18 cm blind zone the browser mutes anyway
        # — true of this rig's ringdown extent, not guaranteed in general.
        # `dead` from the scale BEFORE this frame's update: a genuinely
        # variance-free bin never accumulates anything, so its pre-update
        # scale stays 0 forever, while a live bin leaves 0 within a frame or
        # two. Judging after the update would let the very wobble we want to
        # mute be the thing that un-mutes its own bin.
        sig = np.where(was_dead, np.inf,
                       np.maximum(self.scale * MAD_MEAN_TO_SIGMA, NOISE_FLOOR))
        # running-mean handoff, not EMA convergence: sa = max(alpha, 1/n)
        # makes the scale a literal running mean until here, which is exactly
        # where 1/sqrt(n) stops being the right form for its uncertainty
        warm = 1.0 / self.scale_alpha if self.scale_alpha > 0 else float("inf")
        # float(), not an np.float64: promoting sig to float64 mid-stream
        # doubled the per-frame allocation from frame 21 onwards
        eff = max(self.n - 1, 1)
        inflate = float(1.0 + SCALE_CONFIDENCE * max(
            0.0, 1.0 / np.sqrt(eff) - 1.0 / np.sqrt(warm)))
        sig = sig * inflate
        if self.n <= SCALE_SEED_FRAMES:
            # and stay silent outright while the scale is built from a
            # handful of samples: one second of silence when a stream opens
            # is a cheaper honest price than a click
            return np.zeros_like(out)
        return out / sig
