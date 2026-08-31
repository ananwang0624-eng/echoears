# echoears

Listen to the space around you. Two ultrasonic sensors on the temples of a
pair of glasses ping the room nineteen times a second; the echoes come back
as sound — left temple to your left ear, right to your right. Near is early
and loud, far is late and quiet, and a still room is honest silence.

**Try it now (no hardware):** <https://ananwang0624-eng.github.io/echoears/>
— pick **Hand sweep**, press **▶ Play**, and listen to a hand moving between
20 cm and 1 m. Then switch Data to **⚠ RAW counts** to hear what the signal
sounds like *before* the processing — that A/B is the whole project in
thirty seconds.

*Final project for **Advanced Coding Tools and Methodologies (ACTAM)**,
Politecnico di Milano, A.Y. 2025/26 — solo project by
[ananwang0624-eng](https://github.com/ananwang0624-eng).*

*Zero runtime dependencies · 79 unit tests · CI re-derives every documented
number from the shipped demo data (`tools/check_docs.py`)*

![The rig: two ICU-10201 ultrasonic transducers in printed temple mounts on
a glasses frame, flex-cabled to the SmartSonic EVK](docs/img/rig.jpg)

![40 s hand sweep through the pipeline: push-pull cycles 30–110 cm, per-bin
noise sigmas](docs/img/hand.png)

Two sensors (ids 2 and 3), four channels, **233 cm at 19.2 Hz**. Everything
also runs from recorded `.npz` with no board attached, through the identical
audio path — the web app (`web/`) has sonar / targets / tones / sweep
listening modes, a 2×2 channel A-scan grid, a waterfall, and a per-channel
mixer.

> **Picking this up cold?** Read [HANDOFF.md](HANDOFF.md) first — hardware
> geometry, the range model, the invariants that cost real debugging time, and
> the corrections not to re-derive wrongly.

## Run it

Open the repo in VS Code and press ▶ Run on a script in `run/` — see
[run/README.md](run/README.md). First time: `2_apply_queue.py`, then
`1_listen.py`.

From a shell, if you prefer:

```bash
python -m pytest tests/ -q
python apps/live.py --odr 4 --seconds 60          # hardware, 120 cm
python apps/live.py --replay <session.npz> --odr 6 # no hardware
python apps/show.py <session.npz> --odr 6 --static
```

The EVK driver stack is Python 3.9; use the sibling repo's venv:
`~/Documents/GitHub/ultrasonic/.venv-py39/bin/python`. The `run/` launchers
re-exec into it by themselves.

## Capture configuration

One config: the **two-sensor temple pair** (`p2x2_txrot_pair23`, ids 2 and 3,
4 channels) at **233 cm / ODR 4 / 302 samples / 0.78 cm per bin / TX 160
cycles / 19.2 Hz**, installed by `run/2_apply_queue.py`.

TX length is the half everyone forgets: the RX window sets how far you
*listen*, the TX burst sets whether that far still contains signal. The
16-cycle burst the queues inherited left everything past ~65 cm in the
noise; the 160-cycle vendor Long Range burst measured +9 dB at 0.5–1 m and
real echoes to ~1.2 m (datasheet caps the part at 1.7 m wall / 1.1 m post).
The RX opens 0.91 ms after TX onset, when the burst ends, so the axis
begins at 16.3 cm. Closer than that is **not** a blind zone: an echo is as
long as the burst that made it, so a 15 cm target still delivers 96.5% of
its energy into the receive window — it is range-AMBIGUOUS, piling into the
first bin, weaker the closer it gets (64% at 10 cm, 32% at 5 cm). And the
ringdown that does dominate the near field — peaking at 19.5-21 cm, 2400x
the far-field floor — is flattened by per-bin normalisation, not by muting:
the near-field residual measures 1.6-2.0 sigma at p95 with 0.00% over the
3.5 sigma gate, the same as the far field. The blind-zone slider therefore
defaults to 0.

Archived recordings predate this tool and were captured at ODR 6 (22 cm) —
replay and inspection read them fine, the axis is per-file via `--odr`.

## The mapping

```
time within a grain  =  distance      (near echoes sound early)
grain amplitude      =  echo strength
grain rate           =  sensor frame rate (25.6 Hz -> real time)
pitch                =  distance again, redundantly (near = high)
```

Four listening modes, one mixer:

**Ping** (default) — sonar. A short tick, then the profile rendered as its
echo train: an echo at distance d returns at a delay proportional to d,
scaled in dB by strength, through a generated reverb. Distance = delay is
the physical mapping itself — the ~14 ms ultrasonic echo train slowed tens
of times (~x46 at the default ping period) into human time (the mirror of TerraTone, which speeds seismograms up
1100x). No peak tracking to churn; the ~1 Hz repetition is a rhythm, not a
pitch.

**Targets** — the hardware's own decision rule, run on the host: the
vendor's absolute threshold curve (from the installed meas queue) over RAW
counts, up to 5 targets per channel, each a steady tone. This answers
"what IS there" where the other modes answer "what changed": a still wall
at 80 cm is a permanent tone, and there is no noise floor at all. Measured
on the recordings, its strongest target sits at 81 cm with ±3 cm
frame-to-frame jitter, against ±56 cm for the adaptive sigma rule — the
on-chip algo slot is occupied by our TX-rotation firmware, so this is that
algorithm's judgement recreated host-side (tools/check_docs.py verifies
the threshold copy against the queue file).

**Tones** — persistent sine voices driven by peak-picked echoes (pitch =
log distance, near = high). Voices are sticky (nearest-bin matching) with
hysteresis (born loud, survive quiet) and fast-attack / slow-release, so
the bank no longer reshuffles and warbles at the frame rate.

**Sweep** — the original audification: one grain per frame, time within the
grain = distance. Kept as the honest raw view, but gated the same way.

## Hardware

A glasses frame with 3D-printed sensor mounts carrying two TDK **ICU-10201**
ultrasonic transducers (PMUT time-of-flight sensors, ~175 kHz), one per
temple, facing forward — id 3 on the wearer's left, id 2 on the right. Flex
ribbons run to a TDK SmartSonic evaluation board, which talks to the laptop
over USB. The extra mount at the bridge is left over from an earlier
three-sensor experiment and is unused here.

No electronics were designed for this project: the sensors and the EVK are
stock, the frame is printed — everything downstream of the USB cable is this
repository. The sensors fire and listen themselves (pulse-echo); the host
does the DSP, the detection, and the sound.

## Web Audio, mapped

Everything audible in the browser is raw Web Audio API — no wrapper library:

| What | Where |
|---|---|
| Synthesis — sticky `OscillatorNode` voices; phase-continuous granular scan-sweep | `web/js/audio.js` |
| Routing — per-channel strip → `StereoPanner` → master bus | `web/js/audio.js` |
| Effects — generated-IR `ConvolverNode` reverb, `BiquadFilter` lowpass, `DynamicsCompressor` | `web/js/audio.js` |
| Parameter automation — `setTargetAtTime` slewing on gain/detune (no zipper noise) | `web/js/audio.js` |
| Analysis — `AnalyserNode` output spectrum, drawn live | `web/js/scope.js` |
| Offline synthesis in Python — same mapping, rendered to WAV | `echoears/sonify.py` |
| Live transport — dependency-free stdlib RFC-6455 WebSocket bridge | `tools/bridge.py` |

## Units: noise sigmas, not counts

Raw echo magnitudes span **~70 dB across the range axis** — the transducer
ringdown at 20 cm is ~2400x the level at 2 m — so no single threshold or
loudness curve can serve both ends. A gate tuned near silences everything
far; one tuned far lets ringdown residue through as a phantom target. Every
auto-gain scheme layered on top of that is chasing a moving target.

So the pipeline normalizes each range bin by **its own measured noise**:
subtract the per-bin temporal median, divide by the per-bin MAD. The output
is in sigmas — "3.5" means three and a half sigma above what that bin does
when nothing is there, at 16 cm and at 250 cm alike.

95th percentile of a static scene, `scene233`, pooling the two pulse-echo
ears. The sigma row is measured **on the shipped `web/data/scene233.bin`**,
so anyone can re-derive it — `python tools/check_docs.py` does exactly that
and fails if this table drifts. (Reading the source `.npz` instead gives
1.69/1.84/1.76/1.89 and 0.94 dB; the difference is the exporter's 0.125 σ
quantisation, and the shipped file is the one a reader can check.)

Note which row is which: the `--raw` demo dataset ships **raw magnitudes**
(57.6 dB); the 33.8 dB row is what is left after clutter removal, which is
the fair comparison against sigma since sigma is exactly that residue
divided by its own MAD.

| | 20-40 cm | 40-80 | 80-140 | 140-250 | spread |
|---|---|---|---|---|---|
| raw magnitude (what `--raw` ships) | 14932 | 359 | 154 | 20 | **57.6 dB** |
| residue counts (clutter removed) | 394 | 111 | 30 | 8 | **33.8 dB** |
| residue × TVG r^2.0 | 1294 | 1380 | 1156 | 1122 | 1.80 dB |
| **noise sigmas** | 1.75 | 1.88 | 1.75 | 1.88 | **0.60 dB** |

At the default 3.5 sigma, 0.100% (`scene233`) to 0.141% (`empty233`) of
static-scene bins fire overall, on the shipped files. Per band it is still
an ~8x spread, so "one number everywhere" is a claim about the *level*
(0.60 dB flat), not about the tail. A Gaussian tail at 3.5
sigma would be 0.023%, so the residue is several times heavier-tailed than
normal, which is why the threshold comes from the measured curve.

**Why not just a TVG?** Because on flatness alone it is competitive — r^2.0
reaches 1.80 dB, within 0.9 dB of sigma — and pretending otherwise invites
a fair question. Three things it still cannot do. It needs an exponent
fitted empirically (r^2.5, the exponent that matches the measured spreading
slope, gives 6.86 dB; r^1.5 gives 9.28; the best flattener is 2.0 — physics
does not hand you the right one). It is a function of range only, so it
happily amplifies the pinned, variance-free bins that sigma mutes. And it
leaves the threshold in scaled counts, meaning nothing in particular — no
false-alarm rate attaches to it. Sigma also cannot remove fixed clutter on
its own; both approaches need the median/EMA subtraction first.

The web app ships the same recording both ways — pick **⚠ RAW counts** in
the dataset dropdown to see and hear what the un-normalised data does, and
switch back. That contrast is the clearest thing in the project.

The pitch-catch channels are flat too, with one exception worth knowing:
the first five bins of their longer bistatic axis sit inside the transmit
overlap and read LOW (0.7 sigma), not high — the safe direction.

Detection SNR of a *synthetic additive* target at 25% of local clutter also
improved 2-7 dB in three of four bands (the fourth was ~1 dB worse). That
experiment injects energy obeying the same model this normalisation assumes,
so treat it as supporting evidence rather than proof — no capture with real
motion exists yet. The unambiguous win is the flatness, and it let the
browser's decaying auto-gain be deleted outright.

Two things this is *not*. It is not a range-cell CFAR — a CA-CFAR with a
burst-matched guard was built and lost by 1.7-3.3 dB in all eight
band/channel combinations, because its training ring straddles the ringdown
skirt; the clutter here is time-stationary and range-varying, the inverse of
what CFAR assumes. And it is not a physical amplitude: sigma is
significance. A bin with no measurable variance (a pinned, saturated
ringdown cell) is given an infinite scale and muted, because its wobble is
instrument, not scene.

Loudness on top of that is `(x/8)^gamma`, compressive, so weak-but-real
echoes stay audible.

The terminal path (`apps/live.py`, `apps/play.py`) runs the same units and
the same 3.5 σ gate. Close to what the browser plays, not identical: the
browser also mutes a near-field blind zone and defaults to sonar mode,
while the terminal path is the sweep engine with no blind zone. Measured on 200 frames of a static desk scene where nothing moved:
the old counts path filled every single grain with auto-gained noise (0%
near-silent, crest 19 dB), the sigma path is near-silent in 83% of grains
and loud only where something is (crest 38 dB). Silence on a still scene is
the correct answer, and the old auto-gain could not produce it.

Both modes share a noise gate and a near-field blind zone (sliders): a 50 ms
grain repeated at 20 Hz is a periodic excitation whose spectrum is lines
spaced 20 Hz apart — motorboating — and the ringdown residue used to fire a
loud high blip at the start of every grain. Gate + blind zone remove the
spurious excitation; the tone bank removes the periodicity itself.

Carrier phase is integrated across the whole signal rather than per grain, so
grain boundaries produce no discontinuity and therefore no clicks.

### The other two channels

Two sensors do not give two channels, they give four: each sensor receives its
own transmission (**pulse-echo**, tx == rx, an echo at range *r* arrives at
2*r*/c) and also the other's (**pitch-catch**, tx != rx, whose constant-delay
locus is an ellipse with the two sensors as foci, not a circle).

The web app now streams and shows all four. The PE pair is the instrument —
on, hard-panned left and right. The PC pair is off by default and an octave
down when you enable it: its job is to referee, not to sing. If a PE peak is
real, the PC channels see the same object at a bistatic path length that the
2x2 grid makes obvious; if it is ringdown or a sidelobe, they do not.

## Range: what sets what

This is the one thing that is easy to get silently wrong.

```
range      <- total RX instruction length, in SMCLK cycles
samples     = rx_smclk / smclk_per_sample
resolution <- smclk_per_sample, i.e. the CIC ODR
```

**ODR does not set the range.** It sets how finely the listening window is
sliced. Its practical role is the buffer ceiling: `IQ_SAMPLES_MAX = 340`, so at
a fine ODR you run out of buffer before you run out of listening time.

| CIC ODR | SMCLK/sample | PE step | PE reach @115 | PE reach @340 |
| --- | --- | --- | --- | --- |
| 6 | 32 | 0.196 cm | 22.5 cm | 66.6 cm |
| 5 | 64 | 0.392 cm | 45.1 cm | 133 cm |
| 4 (current queue) | 128 | 0.784 cm | 90.2 cm | 267 cm |
| 3 | 256 | 1.568 cm | 180 cm | 533 cm |

`smclk_per_sample` is **not stored in the npz** — the CaptureConfig has no
CIC-ODR field — so every function takes it explicitly and `--odr` is a required
flag. The upstream repo hardcodes 32 in `matrix/frames.py`, correct only while
the meas queue says `odr: 6`; change the queue and every axis is silently
mislabeled with no error. That is the bug this package refuses to inherit.

`profile.rx_smclk_for_range()` goes the other way: given a target range, how
long the RX instruction has to be.

## Layout

```
echoears/
  session.py   standalone schema-v1 npz reader (no cross-repo import)
  profile.py   IQ -> magnitude, range axis, clutter removal (batch + streaming)
  sonify.py    profile -> audio (batch + per-frame GrainSynth), WAV writer
  sources.py   ReplaySource | LiveSource (wraps the ultrasonic repo's Rig)
apps/
  live.py      binaural listening: hardware or --replay
  show.py      session info + ASCII range profiles
  play.py      sonify a whole session to WAV
tools/
  measqueue.py plan / show / write a meas queue (via the vendor CfgWriter)
  use_queue.py point the txrot plugin at a queue; status; restore
  export_web.py session npz -> uint8+JSON for the browser
  bridge.py    RFC-6455 WebSocket server: live frames -> browser
  record.py    live rig -> schema-v1 npz
web/           the web app: index.html + ES modules, zero dependencies
  js/audio.js  sonar / tones / sweep engines, per-channel mixer strips
  js/scope.js  A-scan, 2x2 grid, waterfall, spectrum (canvas)
  data/        recorded sessions exported for the browser
run/           click-to-run launchers for VS Code
tests/
  test_core.py    pure functions, no files or hardware needed
  test_capture.py capture round-trip on a fake source
```

`apps/show.py` is deliberately not named `inspect.py` — that shadows the stdlib
module and breaks `dataclasses`.

## Verified on real data

`hand_moving` session, 770 frames @ 25.64 Hz, 9 channels × 115 samples:

- raw profiles peak at **1.4–3.1 cm** on the pulse-echo channels — transducer
  ringdown, not a target
- with `--static` (temporal median removed) the peaks move to **5–10 cm** (PE)
  and **9–16 cm** (PC) — that is the moving hand
- channels 5 (2→3) and 7 (3→2) both show a 14–16 cm feature, the reciprocal
  pair the upstream vault records as the reciprocity check

## Known limits

- Archived recordings cover **0–22.4 cm** (115 samples at ODR 6). Nothing
  beyond that is attenuated — it was never digitized: a target at 30 cm returns
  its echo at 1.75 ms and that acquisition window closed at 1.30 ms. Only new
  captures get the 120 cm reach.
- Live capture needs the 120 cm queue installed (`run/2_apply_queue.py`);
  `run/1_listen.py` refuses to start without it, because a wrong axis is
  silent, not an error.
- Re-running the upstream `setup_mac_py39.py` reverts the plugin registry;
  re-run `2_apply_queue.py`. `3_queue_status.py` tells you.
- `TX-MUTED` / `LINK-DEAD` on startup is handled automatically: bring-up
  failures run the upstream recovery ladder (API reset, soft reset, LDO
  power-cycle) and retry, 3 times by default (`--attempts`). Only a board the
  ladder itself cannot revive reaches you.
- The PMUT Q factor is unknown upstream (a simulation placeholder, not a
  measurement), so no claim is made here about physical range resolution.
