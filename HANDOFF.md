# Cold-start handoff — echoears

Read this first if you are picking this up from zero. Written 2026-08-28.

Everything below marked **verified** was measured in-session on real hardware or
real data. Everything marked **unverified** is not. Do not promote one to the
other without running it.

---

## 1. What this is, and the three repos

**echoears** turns ICU-10201 ultrasonic distance profiles into binaural sound.
Two sensors on the temples of a pair of glasses, facing forward; left sensor to
the left ear, right to the right. It is a *proximity/spatial instrument*, not a
navigation product.

```
~/Documents/GitHub/echoears                  THIS repo. Sonification + web app.
~/Documents/GitHub/ultrasonic                Sibling: the EVK stack, matrix
                                             track, Rig, npz schema. We IMPORT
                                             from it, never modify it.
~/Documents/GitHub/ultrasonic (md)           Its Obsidian knowledge vault.
~/Documents/GitHub/ICU-x0201_EVK-...-3.3.1   The TDK EVK install (PYZ-extracted
                                             into the py39 venv).
~/Documents/GitHub/ACTAM                     Course repo. Holds TerraTone, the
                                             *other* candidate deliverable.
```

**Python is 3.9 and not optional** — the EVK driver stack is py3.9 bytecode.
Use `~/Documents/GitHub/ultrasonic/.venv-py39/bin/python`. The `run/` launchers
re-exec into it, so clicking ▶ Run in VS Code under any interpreter works.

---

## 2. Thirty-second mental model

```
sensor (2 temples)              ~/…/ultrasonic  matrix.runtime.Rig
   |  IQ callbacks
   v
LiveSource.poll()  ──► (ts_us, |IQ| (4 ch, 302 samples))
   |                            dedup by timestamp; never blocks
   v
RunningBaseline  ──► residue (moving stuff only; clutter/ringdown removed)
   |
   +──► GrainSynth  ──► one audio grain per frame, per ear ──► sounddevice
   +──► WebSocket bridge ──► browser (web/)

mapping:  time inside a grain = distance
          grain amplitude     = echo strength
          grain rate          = frame rate (so it is realtime)
          pitch               = distance again, redundantly (near = high)
```

`ReplaySource` produces the identical tuples from a recorded `.npz`, so
everything downstream is testable and demoable with no board attached.

---

## 3. Hardware and geometry (**verified** 2026-08-28)

| | |
|---|---|
| sensors | ids **2 and 3**, on the two temples, **parallel, facing forward**. **id 3 = LEFT temple, id 2 = RIGHT** (confirmed by listening 2026-08-28; the reverse sounded mirrored) |
| baseline | **16 cm** (user-measured) |
| config | `p2x2_txrot_pair23` — 4 channels `[(2,2),(2,3),(3,2),(3,3)]` |
| ears | the two pulse-echo channels: index **0 and 3** |
| fop | ~176.5 kHz, λ ≈ 1.96 mm |
| port | `/dev/cu.usbmodem11301` (autodetected) |

Elevation is unresolvable — both sensors sit at the same height, so the array
is 1-D horizontal. Straight ahead and straight up give the same Δr.

### Azimuth

Only sensor **positions** enter, not their orientation:

```
sin(theta) = Δr / baseline = Δr / 0.16
```

| Δr accuracy | azimuth (boresight) |
|---|---|
| 0.78 cm (one bin) | **±2.8°** |
| 1.57 cm (pulse-limited) | **±5.6°** |

Because orientation does not enter, **parallel forward-facing is correct** and
splaying the sensors outward would buy no resolution while shrinking the
overlap. Phase-based fine ranging is not usable here: λ = 1.96 mm wraps 163
times across ±90°, and the envelope is ~8λ coarse, so the coarse scale cannot
unwrap the fine one.

---

## 4. The range model — the one thing that is easy to get silently wrong

```
range      <- total RX instruction length, in SMCLK. The only knob that
              buys reach; it is how long the sensor listens.
samples     = rx_smclk / smclk_per_sample
resolution <- CIC ODR   (smclk_per_sample = 16 * 2**(7 - odr))
```

**ODR does not set range.** Setting it alone keeps the same window and samples
it more coarsely — the vendor's `rx_length` drops 115 → 29 going odr 6 → 4.

Three ceilings, in the order they actually bind:

1. **the beat** — RX window + readout must fit `odr_ms`. *This is the binding
   one at long range.*
2. the IQ buffer — `IQ_SAMPLES_MAX = 340`
3. SPI readout — ~2 ms per sensor at 115 samples, scales with sample count

### Installed capture point (**verified on hardware**)

```
queue      ~/…/ultrasonic/firmware/txrot/txrot_long233_tx160.json
ODR 4  ·  302 samples  ·  0.777 cm/bin  ·  234.8 cm PE  ·  469 cm PC path
TX 160 cycles (vendor Long Range burst; the old 16-cycle burst left
everything past ~65 cm in the noise — A/B measured +9 dB at 0.5-1 m,
real echoes to ~1.2 m; datasheet caps at 1.7 m wall / 1.1 m post)
TX 0.91 ms + RX 13.69 ms + readout ~10.5 ms = 25.1 ms -> odr_ms 26 -> 19.2 Hz
Axis origin: RX opens 0.91 ms after TX onset (burst end) -> bin 0 is
16.3 cm. NOT a blind zone: the echo is as long as the burst, so a 15 cm
target still lands 96.5% of its energy in the window. Closer targets are
range-ambiguous, piling into bin 0 with energy proportional to range
(64% at 10 cm, 32% at 5 cm). Corrected 2026-08-29 after re-asking
why a long burst would not simply be received later in the same burst —
it is, and the earlier "blind zone" claim was wrong.
```

Read back off the board: `n_samples 302`, axis to `234.8 cm`, **19.2 Hz
measured over 8 s**, calibration converged in 1 iteration.

`smclk_per_sample` is **not stored in the npz** (CaptureConfig has no CIC-ODR
field), so every function takes it explicitly and `--odr` is required. Upstream
hardcodes 32 in `matrix/frames.py`, correct only while its queue says odr 6.
**This package refuses to inherit that.**

> If you go back to recording for the upstream matrix track, run
> `python tools/use_queue.py restore` first. Its `frames.py` assumes its own
> 22 cm queue and will mislabel every cm band with no error otherwise.

---

## 5. What exists

| Path | What |
|---|---|
| `echoears/session.py` | standalone schema-v1 npz reader (no cross-repo import) |
| `echoears/profile.py` | magnitude, range axis, clutter removal + per-bin noise normalisation (batch + streaming), range planning |
| `echoears/sonify.py` | batch `sonify()` + per-frame `GrainSynth` + WAV writer (stdlib `wave`) |
| `echoears/sources.py` | `ReplaySource`, `LiveSource` (wraps upstream `Rig`) |
| `apps/live.py` | binaural listening — hardware or `--replay` |
| `apps/show.py`, `apps/play.py` | ASCII range profiles; whole-session WAV |
| `tools/measqueue.py` | `plan` / `show` / `write` a meas queue via the vendor `CfgWriter` |
| `tools/use_queue.py` | `status` / `set` / `restore` which queue the plugin uses |
| `tools/export_web.py` | npz → uint8 + JSON for the browser |
| `tools/bridge.py` | dependency-free RFC-6455 server, live frames → browser |
| `run/1..7` | click-to-run launchers, prompts with defaults |
| `web/` | static web app: head A-scan, 2x2 channel grid, waterfall, AnalyserNode spectrum, per-channel mixer |
| `tests/` | **79 tests** (test_core + test_capture), pure functions, no hardware or data files |

**Verified:** 79 tests green; tx160 queue on hardware at a clean 19.2 Hz
(A/B: +9 dB at 0.5-1 m, reach ~65 cm -> ~1.2 m); back-to-back bring-ups with
NO replug after the close-time probe landed (the wedge-every-session cycle is
broken); web/data ships real 233 cm 4-channel recordings with correct L/R
(ears [3,0]) and the 16.3 cm axis origin; the web app verified in-browser
against them (blind zone 18 cm = 3 bins, far-wall echo renders, zero console
errors). web replay + live both honour the bridge/exporter ears.

**Hardware run 2026-08-29 — and what it does and does not prove.** An
independent review took these apart; the honest version:

| claim | status |
|---|---|
| the rig streams sigma end-to-end: rig → bridge → browser → audio, protocol 2, 4 ch × 302 @ 19.2 Hz, axis 16-250 cm, ears [3,0], PE r0 16.3/16.4 cm vs PC 32.7 cm | **holds** — an integration fact, and the geometry could have been wrong in a dozen ways |
| cold-start p95 1.85 σ, 0.000% over full scale | **refuted by my own follow-up.** `verify_live.py --repeat 12` samples twelve seeds: p95 is stable (1.6-1.9 σ) but the worst-seed peak reached 10.5 σ and **3 of 12 runs put bins over full scale**. "0.000%" was one lucky seed. Mitigated since (seed silence + a transient confidence inflation) down to 1 of 12 at 0.004% — which is the same order as the settled stream's own 0.001%, so the honest reading is "the warm-up is mildly hotter than steady state", not "clean" |
| flatness 0.61/0.98 dB "matching" 0.94 | **near-tautological**. `to_sigma` divides each bin by its own spread, so p95 lands near 1.8 σ on any static input. The empty control is *less* flat than the desk scene. Do not present this as a result |
| false alarms 0.133% "between the recordings' 0.118/0.170%" | **mismatched estimators**. Those two are the OFFLINE `to_sigma`; the rig ran the STREAMING baseline, which gives 0.093/0.139% on the same files. The conclusion survives, the stated precision does not |
| browser audio "26/26 analyser probes non-zero" | **cannot fail**. The analyser sits after a 1.3 s reverb with pingS 0.8 s, so one voiced ping keeps it non-zero for the session. It proves the graph is connected, nothing more |
| SIGTERM → clean reopen, "recovery ladder never ran" | **uncontrolled, one sample**. `attempts=1` makes the ladder structurally unreachable in `start()`, so that half is a parameter choice, not an observation. There is no unarmed control run, and an unarmed kill earlier in the same session also left the board recoverable |

`tools/check_docs.py --strict` re-derives every mechanically checkable
number in the docs against the code and the shipped data, and runs in CI —
documented numbers drifted three times in one working session, each caught
only on a later re-read, never at edit time. `tools/verify_live.py` re-derives the
signal-processing ones, on the rig or from a file, and
says in its own docstring which numbers can and cannot discriminate. A
claim nobody can re-run is not evidence; the 35 s capture was not saved,
which is why the script has `--save`.

**Pre-push checks, done so the first push cannot fail publicly:**
- CI (`.github/workflows/ci.yml`) has never run, because nothing was ever
  pushed. Reproduced its environment exactly — a clean venv with only
  `numpy pytest`, no EVK anywhere — and the suite is **63 green**. The
  "hardware paths are import-guarded" comment in the workflow is true.
- GitHub Pages serves at `user.github.io/echoears/`, i.e. a SUBPATH. Served
  `web/` from `/echoears/` locally: index, `js/main.js`, `css/style.css`,
  `data/*.json` and `data/*.bin` all 200, the app boots, builds four mixer
  strips, resolves ears [3,0], zero console errors. No path fixes needed —
  every reference in the page is relative.

**Not verified / open:** nobody has *listened* on headphones at the rig since
the tx160/sonar rework; the shipped scene233
recording contains no hand motion — re-record with a hand in frame;
GitHub push + Pages still pending.

---

## 6. Non-obvious invariants (each cost real debugging time)

1. **A sensor-set mismatch is a config error, not a wedged board.** Resetting
   hardware cannot conjure a sensor that is not plugged in, and running the
   recovery ladder against a healthy board is how you actually wedge it — that
   happened here. `LiveSource` now fails fast on mismatch and names the config
   that matches the sensors present.
2. **`assemble_frames` re-returns the whole rolling buffer every call** (~2 s of
   frames). Dedup by timestamp or you republish ~50 frames per tick.
3. **Never block in the frame consumer.** A slow consumer starves the serial
   reader thread; upstream documents this as the board-wedging failure. The
   bridge drops a dead socket rather than raising; the audio queue drops rather
   than blocks.
4. **Resolve user paths before importing the EVK stack.** `common/evk/bootstrap`
   `os.chdir()`s into the EVK install on import, so relative paths move.
5. **Do not name a script `inspect.py`.** It shadows the stdlib module and
   `dataclasses` fails to import. (`apps/show.py` exists for this reason.)
6. **`python -c` is unsafe here** — cwd goes first on `sys.path` and the EVK
   clone's Windows package dirs shadow real wheels. Use script files.
7. **No agent fleets / batch analysis during hardware capture.** Upstream logged
   a real incident: background CPU load starved the serial thread, 485 bad
   beats, frame desync.
8. **`odr_ms` must fit the queue.** `p2x2_txrot_pair23` ships 13 ms, written for
   the 22 cm queue. `LiveSource(odr_ms=…)` overrides it via
   `dataclasses.replace` so the upstream repo stays untouched.

---

## 7. Corrections made — do not re-derive these wrongly

| Claim | Correction |
|---|---|
| "PMUT Q ≈ 51, so range resolution is 4.96 cm" | Q is **unknown**; 50 is a simulation placeholder in the upstream vault. No resolution claim is made anywhere in this repo. |
| "PC channels cover 45 cm" | That is **bistatic path**, not object range. Object range is also ~22 cm at odr 6. |
| "The PC direct path is a tripwire between the temples" | True on the old 3.1 cm bench, **not transferable**: 16 cm apart and 90° off-axis at both ends. Weak direct coupling is bad for a tripwire but *good* for PC near-field sensitivity. |
| "Left sensor → left ear gives correct ITD" | It does not. That is two independent monaural streams hard-panned — level/onset differences, not interaural time difference. Real ITD needs deriving an angle and rendering with `PannerNode` HRTF. |
| upstream `HANDOFF.md:167` range formula `c*32*2**ODR/(16*fop)` | **Wrong** — gives 2048 SMCLK/sample at odr 6. Correct is `16*2**(7-odr)`. `frames.py` is right; the prose is not. |
| planner recommends by buffer + readout | Also had to model the **RX window**; it was recommending queues that cannot fit their beat. Fixed. |

---

## 8. ACTAM course context

**Defence 2026-09-01.** Hard requirements, from the course `intro.md`:

- must be a **web application**
- code and docs on **GitHub**
- an accompanying **GitHub Pages** site

Graded on: technical implementation, creativity, **user experience**,
**concept integration** (i.e. using the Web Audio API / Tone.js taught in the
course), complexity, **documentation**.

This is why `web/` exists: the Python side alone does not satisfy the
requirement, and a grader opening the Pages URL must see something that works
without hardware. `web/js/audio.js` deliberately uses `AnalyserNode` — the
realtime spectrum is exactly what it is for, and it is the honest counterpart
to the hand-written offline FFT in the sibling TerraTone project.

> **Unknown:** the defence duration. It determines how much demo fits.

### The other candidate

`~/Documents/GitHub/ACTAM` holds **TerraTone** (earthquake audification) —
finished (TerraTone: 35 tests), full docs, slides, offline fallback. Its only gap is that
GitHub Pages was never set up. It remains a complete fallback deliverable.

---

## 9. Open items

**Not done:**
- Nothing is pushed. No remote is configured on `echoears`; the Pages and CI
  workflows are written but have never run.
- `web/data/` ships 233 cm captures, but BOTH are static: scene233 was
  recorded unattended and empty233 is the control. They are statistically
  indistinguishable, so there is no scene-vs-empty A/B. The single highest
  value 40 seconds left in this project is a capture with a hand actually
  moving in it — everything else is verified, that is not.
- The 233 cm configuration has not been listened to yet.

**Next measurement (5 minutes, gates a design decision):** record ~5 s of empty
scene and look at the PC channels' near field. Structure-borne coupling through
the rigid frame would appear as a spike at a very short apparent range and
would have to be masked out. This decides whether PC can act as the pairing
referee described below.

**The PC channels are still unused.** Only the two PE channels are voiced. PC
is not a third sound source — its value is geometric:

- PE gives **circles** around each sensor; PC gives an **ellipse** with the two
  sensors as foci. Together they localise in 2-D.
- With two targets (e.g. the two boards forming a gap), each PE channel shows
  two peaks and there are 4 possible pairings, 2 of them wrong. Predict the PC
  path for each candidate and check whether energy is actually there — **that
  is what PC is for**.
- PC is also not blinded by the transmitter's own ringdown, so it can see
  closer than PE.
- The two PC channels are near-reciprocal (upstream measured `(2,3)` 15.1 cm /
  4514 vs `(3,2)` 15.2 cm / 4293), so averaging them is ~3 dB for free.

**Demo design under discussion.** A six-act live performance was proposed;
after review three acts survive as low-risk and reproducible in the web app:
the single-ping "bat's glimpse", the material stethoscope (metal / glass /
wool — the project's own data already shows material-dependent echo energy),
and an honest-failure act (a smooth panel at 45° disappears specularly). The
"walk through the gap" act needs the 233 cm range that now exists, but also
needs the PC pairing referee above. Acts that depend on a volunteer performing
live are the high-variance part.

The user has bone-conduction headphones and can bring hardware to the defence.
