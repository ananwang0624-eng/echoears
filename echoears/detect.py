"""Hardware-style target detection, run on the host.

The ICU-10201's on-chip rangefinder cannot run here — its algo slot is
occupied by our txrot TX-rotation firmware — but its DECISION RULE is just
an 8-segment absolute threshold curve over range bins, and that curve is
sitting in the installed meas-queue JSON. This module applies exactly that
rule, so the output is what the chip would have reported.

Why absolute thresholds and not the sigma pipeline: the sigma path answers
"what CHANGED" (clutter removal first), which erases the room. This answers
"what IS THERE" — a still wall at 80 cm is a target, permanently. Measured
on the real recordings, the strongest target under this rule sits at 81 cm
with +-3 cm frame-to-frame jitter; the sigma rule's "strongest" bounced
+-56 cm because it was picking noise.

Ringdown: the vendor curve was designed assuming on-chip ringdown
cancellation over the first RINGDOWN_BINS samples (its first segment is a
LOW 1200 counts — meaningless against a ~18000-count raw ringdown). That
filter lives inside the rangefinder algo we cannot run, so we do the same
job host-side: subtract a slow static estimate (offline: temporal median;
live: the RunningBaseline's baseline) in that region before thresholding.
With no estimate available the region is blanked instead.
"""

from __future__ import annotations

import numpy as np

#: The threshold curve of the installed queue (txrot_long233_tx160.json,
#: meas_cfg[0]). Duplicated here so echoears needs no path into the
#: ultrasonic repo at runtime; tools/check_docs.py verifies this copy
#: against the queue file and CI fails if they drift.
STOP_INDEX = [40, 45, 50, 60, 130, 160, 190, 220]
THRESHOLD = [1200, 5000, 2500, 1000, 200, 175, 150, 125]

#: Samples the vendor curve expects ringdown cancellation over — the region
#: its 1200-count first segment is calibrated for. Measured on scene233 the
#: ringdown peaks at bins 4-6 (19.5-21 cm) at ~16000 counts, 2400x the far
#: field, and is still ~30x the floor at bin 40; 40 covers the lump.
RINGDOWN_BINS = 40

#: MAXTARG in ch-rangefinder/structs.h.
MAX_TARGETS = 5


def threshold_curve(n_bins: int) -> np.ndarray:
    """Piecewise-constant vendor curve, one value per range bin."""
    curve = np.empty(n_bins, dtype=np.float64)
    prev = 0
    for stop, val in zip(STOP_INDEX, THRESHOLD):
        curve[prev:min(stop, n_bins)] = val
        prev = min(stop, n_bins)
    curve[prev:] = THRESHOLD[-1]
    return curve


def detect_targets(mag: np.ndarray, curve: np.ndarray,
                   static_est: np.ndarray | None = None,
                   max_targets: int = MAX_TARGETS) -> list[tuple[int, float]]:
    """One frame of raw magnitudes -> [(bin, over), ...], strongest first.

    `over` is magnitude / threshold at that bin — "how many times over the
    line", a unitless loudness the synth can use directly.
    """
    work = np.asarray(mag, dtype=np.float64).copy()
    rd = min(RINGDOWN_BINS, len(work))
    if static_est is not None:
        work[:rd] = np.clip(work[:rd] - static_est[:rd], 0.0, None)
    else:
        work[:rd] = 0.0

    over = work / curve[: len(work)]
    hits = [i for i in range(1, len(work) - 1)
            if over[i] > 1.0 and work[i] >= work[i - 1] and work[i] >= work[i + 1]]
    hits.sort(key=lambda i: -over[i])
    return [(i, float(over[i])) for i in hits[:max_targets]]
