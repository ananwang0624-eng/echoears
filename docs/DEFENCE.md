# DEFENCE.md — ACTAM defence runbook, 2026-09-01

Terse, runnable, honest. Every number below is sourced from this repo
(README.md, HANDOFF.md, run/, web/, tools/). Where something is **unverified**
it says so and the script routes around it. Defence duration is unknown —
confirm it, then cut Demo A from the bottom up.

---

## 1. 90-second elevator story · 90 秒开场

> EchoEars puts two ICU-10201 ultrasonic transducers on the temples of a pair
> of glasses. They fire ~175 kHz pings — three octaves above hearing — and
> record the echo profile 19.2 times a second, out to 2.5 m. The system moves
> that inaudible signal into the ear, binaurally: left temple to left ear,
> right to right.

One sentence per listening mode (say all three):

- **Sonar** (default): *the mapping is the physics itself* — a tick marks the
  emission, each echo returns after a delay proportional to its distance. The
  real ~14 ms echo train is stretched tens of times into human time.
- **Tones**: strongest echoes each drive a continuous voice, pitch = log
  distance, near = high — sticky voices that glide instead of warbling.
- **Sweep**: the raw audification, one gated grain per frame — kept as the
  honest control so the audience can hear what the engineering fixed.

The TerraTone mirror (concept-integration point — say it explicitly):

> My other project, TerraTone, speeds seismograms up ~1100× to bring
> sub-audible earthquakes *up* into hearing. EchoEars is the mirror: it slows
> ultrasonic echo trains *down* tens of times to bring them into hearing.
> Same idea — time-scaling a real physical signal into the audible band —
> from both ends of the spectrum.

Course axes covered: creativity (a sonar you wear and hear), concept
integration (raw Web Audio API: AudioContext graph, `AnalyserNode` spectrum,
`setTargetAtTime` slewing, phase-continuous synthesis).

---

## 2. Demo script A — hardware on stage · 硬件现场演示

Setup: board on USB, headphones/output connected, repo open in VS Code.

1. **Launch.** Open `run/8_web.py`, press ▶ Run. Terminal shows, in order:
   - `[launcher] switching to …/.venv-py39/bin/python` (re-exec into EVK py3.9)
   - banner `网页版实时收听 (233 cm, 2×2 通道)`
   - `✅ 队列已是 txrot_long233_tx160.json(233 cm)` — if instead it says the
     queue is wrong, it exits and tells you to run `run/2_apply_queue.py` first
   - browser opens `http://localhost:8080` automatically
   - `[bridge] ws://localhost:8765 — 等待浏览器连接`
   - board boots (~20 s: flash + phase calibration), then
     `[bridge] 实时 19.2 Hz, 耳朵=ch3/0 — Ctrl-C 停止`
2. **Connect.** Only after the `实时 … Hz` line: click **Live 连接实时硬件**
   (top right). If you click early, the page retries every 2 s for up to 40 s
   and shows a countdown — that is fine, narrate it. Status turns
   "Live stream connected"; the meta line shows `4 通道 × 302 格 · 19.2 Hz ·
   16–251 cm`. Play/Speed grey out (live has no transport).
3. **Sonar walk (the core 60 s).** Mode = Sonar. Have a target (your hand, a
   book, a volunteer) move toward/away in the **0.3–1.2 m** band — that is the
   verified sweet spot (TX 160-cycle burst: +9 dB A/B over the old 16-cycle
   at 0.5–1 m, real echoes to ~1.2 m; below ~16 cm returns are
   range-ambiguous — they pile into the first bin, weaker the closer).
   - Hear: tick … echo. Approach → the echo slides toward the tick and gets
     louder. Left of the head → louder/earlier in the left ear.
   - See: head-view A-scan peak moves inward; waterfall draws a sloped streak
     (slope = approach/recede); readouts show Left/Right peak in cm.
4. **Switch to Tones.** Same motion: pitch rises as the target nears (near =
   high, log-distance). Point out voices glide — no per-frame warble.
5. **Switch to Sweep, teach with sliders.** This is the "show your
   engineering" segment:
   - **Gate** (default 3.5 σ): drag to 0 → the noise floor is voiced and you get
     the motorboating buzz — a 50 ms grain repeated at ~20 Hz is a periodic
     excitation, spectral lines 20 Hz apart. Restore → silence between real
     echoes. One slider demonstrates why the gate exists.
   - **Blind zone** (default 0): per-bin normalisation already flattens the
     ringdown — near-field residual measures 1.6–2.0 σ at p95, same as the
     far field, so the slider ships at 0 and stays there.
   - Back in Sonar: **Ping period** (default 0.8 s) — shorten to 0.3 s for a
     faster update rhythm, stretch to 2 s to let one echo train breathe.
6. **Mixer, 15 s.** Enable a PC strip (off by default, −1 octave): the 2×2
   grid shows the cross channel seeing the same object at roughly twice the
   labelled range (bistatic tx→target→rx path). One line: "the cross channels
   are the referee, not a third voice."
7. **Spectrum panel.** Point at it: `AnalyserNode`, the actual output signal —
   course API, used for exactly what it is for.

**Unverified — do not promise on stage:** nobody has listened on headphones
at the rig since the tx160/sonar rework. Step 3 of the pre-flight (§6) closes
this gap the morning of. If pre-flight fails, run Demo B and say so.

---

## 2a-bis. Targets mode — the chip's own rule · 目标模式

Switch Mode to **Targets**. One steady tone = one object; the desk sits at
~81 cm with ±3 cm jitter. The committee line: *"The on-chip rangefinder's
slot is occupied by my TX-rotation firmware, so I run its exact decision
rule — the vendor's threshold curve from my own measurement queue — on the
host. On these recordings it is 20x more stable than my adaptive threshold
(±3 cm vs ±56 cm), because it answers 'what is there' rather than 'what
changed'."* If asked about ringdown: the curve assumes cancellation over
the first 40 samples; that filter lives inside the algo we displaced, so
the host subtracts the static estimate there — same job, other side of the
SPI bus.

## 2b. The one-click beat: raw vs normalised · 原始 vs 归一化

The strongest 30 seconds available, and it needs no hardware. Dataset
dropdown → **⚠ RAW counts**, then back.

**Raw** (same recording, no per-bin normalisation): the head view is one
lump near the middle and flat grass everywhere else; the readouts pin to
~20 cm. **Show the shape, not the gate** — the gate sweep sounds the same
across most of its travel on this file (measured: 1.41 peaks per frame from
0.1 to 6.0 σ-equivalent), so do not promise the committee an audible sweep.
The picture is the argument: the near field is ~2400× the far field and one
threshold cannot serve both ends.

**Back to the normalised set**: the same recording, now flat. 95th
percentile across four range bands, PE ears — what the raw file actually
holds: 14932 / 359 / 154 / 20 (**57.6 dB**); after clutter removal
394 / 111 / 30 / 8 (33.8 dB); in noise sigmas 1.75 / 1.88 / 1.75 / 1.88
(**0.60 dB**, measured on the file the page actually loads). Quote the 57.6 for the picture on screen and the 33.8 only
if you say "after clutter removal" — they are different quantities and an
examiner can check both.

At 3.5 σ, 0.100% of static bins fire on `scene233` and 0.141% on
`empty233` — run `python tools/check_docs.py` on the day to confirm the
slides still match the data.
Do **not** say "the same rate at every distance": per band it is 0.020 /
0.028 / 0.099 / 0.163%, an 8× spread. The flat thing is the *level*, not
the tail.

**The line to say:** *"The processing that mattered was not a filter. It was
choosing the right unit — each range bin divided by its own measured noise,
so the number means significance instead of amplitude, and one threshold
finally means one thing everywhere."*

**If asked why not a time-varying gain** — answer honestly, the number does
not favour us: a fitted r^2.0 TVG reaches 1.80 dB, within 0.9 dB of sigma.
Flatness is not the argument. The argument is that its exponent has to be
fitted empirically (r^2.5, the physically motivated one that matches the
measured spreading slope, gives 6.86 dB; r^1.5 gives 9.28), that being a
function of range only it amplifies the pinned variance-free bins that
sigma mutes, and that it leaves the threshold in scaled counts with no
false-alarm rate attached to it. Both still need the clutter subtraction
first; neither replaces it.

---

## 3. Demo script B — no hardware, or hardware dies · 无硬件预案

> **Do not promise a scene-vs-empty A/B.** Both shipped recordings are
> static and are statistically indistinguishable (mean σ per range band
> 0.42/0.42/0.43/0.44 vs 0.41/0.42/0.42/0.46; 17% vs 19% of frames with any
> echo above the 3.5 σ gate). The honest no-hardware story is the raw-vs-
> normalised comparison in §2b, which is a real, visible difference. Say
> plainly that a quiet room pings into near-silence and that this is the
> pipeline being correct, not broken.

Same page, same audio path, recorded data. Framing to say out loud, verbatim
honest: *"This recording is a static desk scene, captured unattended — there
is no hand motion in it. It demonstrates the full rendering pipeline and the
room's fixed geometry; the motion story needs the live rig."*

1. Run `run/8_web.py` with **no board plugged in**. It detects the absence
   and starts the bridge in replay: `🔌 没插板子 — 桥接器用录音回放:scene233.npz`.
   Click Live as before — identical wire format, identical page.
2. Or skip Live entirely: the page's own **Play** button replays the shipped
   `web/data/` exports in-browser with zero bridge (this is also what a fresh
   clone gets — `out/` is gitignored, so 8_web.py then prints
   `只开网页,用页面内置的录音回放` and serves the page only).
3. What to show: Desk scene (769 frames @ 19.23 Hz, 4 ch × 302 bins,
   16–251 cm, static clutter removed) — the far-wall echo renders in the
   A-scan (verified in-browser, zero console errors). Then switch dataset to
   **Empty control** and A/B them: what the desk adds to the empty room.
4. All sliders, modes, and the mixer work identically — run steps 4–7 of
   Demo A on the recording.
5. Deepest fallback for a *motion* demo without the board: terminal replay of
   the archived hand-moving session (22 cm, ODR 6, pre-dates this rig):
   `python apps/live.py --replay <session.npz> --odr 6`. Not the web app —
   only use if asked to prove motion works end-to-end.

---

## 4. Likely committee questions · 答辩问答

- **Why not Tone.js / npm dependencies?** The web app is dependency-free ES
  modules on the raw Web Audio API. The synthesis needs sample-level control
  Tone.js does not sell: carrier phase accumulated across grain boundaries
  (a discontinuity in time is a broadband click in frequency), dB loudness
  mapping, sticky voice allocation. The Python bridge is likewise a
  dependency-free stdlib RFC-6455 server, because installing `websockets` into the vendor's
  py3.9 EVK venv is a support burden the demo does not need.
- **What sets the range?** Three separate knobs, commonly conflated:
  **range ← RX instruction length** (how long the sensor listens);
  **resolution ← CIC ODR** (`smclk_per_sample = 16·2^(7−odr)`; ODR 4 →
  0.78 cm/bin); **signal ← TX burst energy** (16 cycles left everything past
  ~65 cm in the noise; the 160-cycle vendor Long Range burst measured +9 dB
  at 0.5–1 m). ODR does *not* set range — its practical role is the buffer
  ceiling (IQ_SAMPLES_MAX = 340 samples). The binding constraint at long
  range is the frame beat: TX 0.91 ms + RX 13.69 ms + readout ~10.5 ms =
  25.1 ms → 26 ms period → 19.2 Hz (measured over 8 s on hardware).
- **Why does the axis start at 16 cm?** The receiver opens 0.91 ms after TX
  onset — an echo returning mid-burst cannot be received. 0.91 ms round-trip
  is ~15.6 cm; the exported axis runs 16.3–250.6 cm. Closer targets are not
  invisible — an echo is as long as the burst that made it, so a 15 cm target
  still lands 96.5% of its energy in the window; it is range-*ambiguous*,
  piling into the first bin. The blind-zone slider therefore defaults to 0.
- **Is left-to-left-ear real binaural localisation?** Honest answer: no —
  it is two independent monaural streams hard-panned, so the cue is level and
  onset difference, not true ITD. Real ITD would mean deriving an azimuth
  (sin θ = Δr / 0.16 m baseline; one 0.78 cm bin ≈ ±2.8° at boresight) and
  rendering through an HRTF `PannerNode`. That is future work; the hard-pan
  already gives usable left/right discrimination for free.
- **What are the two extra channels?** Two sensors give four channels: two
  pulse-echo (tx = rx, circle loci) and two pitch-catch (tx ≠ rx, ellipse
  loci with the sensors as foci). PE is the instrument; PC is the referee —
  a real PE peak must show up in PC at the predicted bistatic path, ringdown
  and sidelobes do not. Off by default, an octave down when enabled.
- **The window is 2.5 m but the datasheet says less?** Yes — datasheet caps
  the part at 1.7 m (wall) / 1.1 m (post). The listening window is
  deliberately longer than the sensor's reach; verified real echoes to
  ~1.2 m. Every bin is normalised by its own noise, so far bins fire at the same rate as near ones — the gate is one number for the whole axis.
- **What is hand-written vs vendor?** Hand-written: the npz session reader,
  all DSP in `echoears/profile.py` (magnitude, range axis, batch + streaming
  clutter removal), `sonify.py` grain synthesis + stdlib WAV writer, the
  WebSocket bridge, the entire web app (audio engines, canvas scopes, mixer),
  the meas-queue planner. Vendor/upstream: the TDK EVK driver stack (py3.9),
  the sibling repo's Rig/matrix runtime (imported, never modified), the
  low-level queue writer (`CfgWriter`), the board recovery ladder.
- **What is verified vs not?** Verified on hardware/real data: 79 unit tests
  green; the 233 cm tx160 queue at a clean 19.2 Hz; +9 dB A/B; back-to-back
  bring-ups without replugging; the web app against real 233 cm recordings
  with correct L/R (left temple = sensor id 3). Not verified: headphone
  listening at the rig since the sonar rework; any physical range-resolution
  claim (the PMUT Q is unknown upstream — a simulation placeholder — so this
  repo deliberately makes **no** resolution claim beyond the 0.78 cm bin
  spacing, which is a sampling grid, not resolution).

---

## 5. Failure drill · 故障预案

- **Board will not come up (`TX-MUTED` / `LINK-DEAD`).** Automatic: the
  launcher runs the upstream recovery ladder (API reset → soft reset → LDO
  power-cycle) and retries, 3 attempts. Only if the ladder itself gives up:
  physically replug USB, Ctrl-C, re-run `run/8_web.py`. Budget ~30 s; keep
  talking through the architecture slide while it boots.
- **Sensor-set mismatch error.** That is a config error, not a wedged board —
  the message names the config that matches what is plugged in. Do NOT
  power-cycle in response (resetting a healthy board is how you wedge it).
- **Bridge never connects.** The page retries every 2 s for 40 s, then says
  `40 秒内连不上桥接器`. Response: unplug the board, Ctrl-C, re-run
  `run/8_web.py` → it falls back to replay automatically (Demo B). Or ignore
  Live and press Play — the in-browser replay needs no bridge at all.
- **No sound.** In order: (1) browser suspended audio — status bar says click
  anywhere on the page, do that; (2) Vol slider; (3) Gate too high — drop it;
  (4) Blind zone slider swallowing the target — if the target is near, lower
  it toward the 16 cm origin; (5) OS output device.
- **Double-launched 8_web.py.** Harmless: the second instance detects ports
  8080/8765 busy and just reopens the page.
- **Everything Python dies.** One command, any machine with the repo:
  `python3 -m http.server -d web` and open `http://localhost:8080` — the
  in-browser replay is fully self-contained.

Fallback ladder, memorise: **live → bridge-replay → in-browser replay →
static server**. Every rung shows the same page.

---

## 5b. Pre-push, already verified · 推送前预检(已做)

Both were run and passed, so pushing is not a gamble:
- the suite is green in a clean `numpy pytest` environment with no EVK, so
  CI will pass on its first ever run;
- `web/` serves correctly from a `/echoears/` subpath, which is how Pages
  will serve it — no relative-path surprises.

What is left is the part only you can do: create the repo, push, set Pages
source to "GitHub Actions", and open the URL once.

## 6. Pre-flight checklist, morning of 2026-09-01 · 当天早上

Run in this order; each step names its expected output.

1. `run/7_test.py` (or `python -m pytest tests/ -q` under the py39 venv) →
   **79 passed**.
2. Plug the board. `run/3_queue_status.py` → active queue is
   `txrot_long233_tx160.json`. If not (e.g. upstream setup was re-run):
   `run/2_apply_queue.py`, then re-check.
3. **The listening gap — mandatory.** `run/8_web.py`, click Live, headphones
   on, walk a hand 0.3–1.2 m. This is the first human listen since the
   tx160/sonar rework; if it sounds wrong, you still have the whole morning
   and Demo B. Verify: tick-then-echo in Sonar, pitch rise in Tones, left
   hand → left ear.
4. *(Optional, 5 min, only if step 3 is healthy)* Re-record a scene WITH hand
   motion (`tools/record.py`, then `tools/export_web.py` into `web/data/`) so
   Demo B also shows movement. The shipped scene233 has none.
5. **GitHub + Pages — course hard requirement, still not pushed.** Configure
   the remote (`https://github.com/ananwang0624-eng/echoears`, the URL the
   page footer already links), push, enable Pages, and open the Pages URL in
   a clean browser: it must reach the in-browser replay with no hardware and
   no console errors. Do not walk into the defence without this.
6. Unplug the board and run `run/8_web.py` once → confirm the replay fallback
   line appears and Demo B plays. Re-plug.
7. Charge/bring: board + USB cable, headphones (bone-conduction pair exists),
   whatever adapter the room's audio needs. Confirm the defence duration and
   trim Demo A to fit.
8. Close every CPU-heavy app before going live — background load starving the
   serial reader thread is a documented board-desync failure upstream.
