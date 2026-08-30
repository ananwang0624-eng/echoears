/**
 * The Web Audio graph.
 *
 *   [pings | voices | grains] -> strip gain -> panner -> master
 *        master -> dry ----------------------+-> lowpass -> compressor
 *        master -> convolver(reverb) -> wet -+      -> analyser -> destination
 *
 * Three listening modes share one per-channel mixer:
 *
 * "ping" (default) — sonar. Every pingS seconds a short "tick" is emitted
 * and the gated range profile is rendered as its echo train: an echo at
 * distance d returns at t = (d / range) * stretch after the tick, scaled
 * in dB by its strength. Distance = delay is the physical mapping itself —
 * the ~14 ms ultrasonic echo train slowed tens of times into human time. There is
 * no peak tracking to churn and the ~1 Hz repetition is a rhythm, not a
 * pitch, so nothing buzzes. A generated reverb gives the room a body.
 *
 * "tones" — each strip owns persistent sine voices driven by peak-picked
 * echoes (pitch = log distance, near = high). Voices are STICKY: a voice
 * follows its peak by nearest-bin matching, appears only above a high
 * threshold and survives down to a low one (hysteresis), attacks fast and
 * releases slow. Without those three the voice bank reshuffles every frame
 * and warbles.
 *
 * "sweep" — the original audification, one gated grain per frame. Honest
 * raw view, kept as the comparison.
 *
 * Units: every profile reaching this file is in PER-BIN NOISE SIGMAS (see
 * echoears/profile.to_sigma). That is what killed the old auto-gain: raw
 * counts spanned ~70 dB across the range axis, so the engine had to chase a
 * decaying reference and a gate meant something different at 20 cm than at
 * 2 m. Now the gate is an absolute number of sigmas — "3" is three sigma
 * above what that bin does when nothing is there, at every range.
 *
 * Loudness: amp = (x/FULL_SIGMA)^gamma, compressive, so weak-but-real
 * echoes stay audible.
 *
 * The blind zone now defaults to 0, and the reasoning that put it at 18 cm
 * was wrong twice over. It claimed objects closer than 15.5 cm are
 * unreceivable because the transmit burst is still firing — but an echo is
 * as long as the burst that made it, so a 15 cm target still delivers 96.5%
 * of its energy into the receive window; it is range-AMBIGUOUS (piled at the
 * first bin), not invisible. And it claimed the near bins needed muting for
 * ringdown, which per-bin normalisation had already handled: measured on
 * scene233, the near-field residual is 1.6-2.0 sigma at p95 with 0.00% over
 * the 3.5 sigma gate — indistinguishable from the far field. All the 18 cm
 * default did was silence bins 0-2, which is exactly where a hand held
 * closer than 15.5 cm lands.
 */

const SR = 44100;
const VOICES = 3;
//: full scale in sigmas — mirrors FULL_SIGMA in data.js
const FULL_SIGMA = 8;   // per strip — hand + torso + wall is already generous

export class EchoAudio {
  constructor() {
    this.ctx = null;
    this.master = null;
    this.analyser = null;
    this.strips = [];
    this.params = {
      mode: "ping",
      fNear: 1800, fFar: 550,   // tones: pitch range, log-mapped.
                                // fFar sits above ~500 Hz on purpose:
                                // bone-conduction sets roll off hard
                                // below that, and far targets at 300 Hz
                                // simply vanished on the actual rig
      gamma: 0.5, gain: 0.6,
      sweep: true,              // sweep mode: chirp vs fixed carrier
      gate: 3.5,                // sigmas below which a bin is silence
                                // (measured: 3.9 is the 0.135% false-alarm
                                //  point on real clutter, 3.0 gives 0.55%)
      blindCm: 0,               // see below — measurement removed the need
      glide: 0.08,
      pingS: 0.8,               // sonar repetition period, s
      wet: 0.25,                // reverb send
    };
    this._freqBins = null;
    this._pt = 0;               // ping timer id
  }

  /** Must be called from a user gesture — browsers block audio otherwise. */
  ensure() {
    if (this.ctx) {
      if (this.ctx.state !== "running") this.ctx.resume();
      return;
    }
    this.ctx = new AudioContext({ sampleRate: SR });

    this.master = this.ctx.createGain();
    this.master.gain.value = this.params.gain;

    const lp = this.ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.value = 4200;
    lp.Q.value = 0.7;

    const comp = this.ctx.createDynamicsCompressor();
    comp.threshold.value = -18;
    comp.ratio.value = 6;

    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.analyser.smoothingTimeConstant = 0.6;
    this._freqBins = new Uint8Array(this.analyser.frequencyBinCount);

    // reverb: 1.3 s decorrelated noise tail — a real IR without shipping one
    const conv = this.ctx.createConvolver();
    const irN = Math.floor(1.3 * SR);
    const ir = this.ctx.createBuffer(2, irN, SR);
    for (let ch = 0; ch < 2; ch++) {
      const d = ir.getChannelData(ch);
      for (let i = 0; i < irN; i++)
        d[i] = (Math.random() * 2 - 1) * Math.exp(-3.5 * i / irN);
    }
    conv.buffer = ir;

    this._wet = this.ctx.createGain();
    this._wet.gain.value = this.params.wet;
    this.master.connect(lp);                    // dry
    this.master.connect(conv);
    conv.connect(this._wet);
    this._wet.connect(lp);
    lp.connect(comp);
    comp.connect(this.analyser);
    this.analyser.connect(this.ctx.destination);

    this._schedulePing();
  }

  ensureStrips(n) {
    if (!this.ctx || this.strips.length === n) return;
    // a channel-count change abandons the old graph — detach it or the old
    // gain/panner nodes keep feeding master forever
    for (const s of this.strips) {
      s.voices?.forEach((v) => { try { v.osc.stop(); } catch {} });
      try { s.gain.disconnect(); s.panner.disconnect(); } catch {}
    }
    this.strips = [];
    for (let i = 0; i < n; i++) {
      const gain = this.ctx.createGain();
      const panner = this.ctx.createStereoPanner();
      gain.connect(panner);
      panner.connect(this.master);
      this.strips.push({
        gain, panner, phase: 0, voices: null, lastProf: null,
        // defaults are filled in by the UI; start silent so an unconfigured
        // channel cannot surprise anyone wearing headphones
        level: 0, pan: 0, octave: 0, on: false, maxCm: 0, r0: 0,
      });
    }
  }

  setStrip(i, { level, pan, octave, on, maxCm, r0 }) {
    const s = this.strips?.[i];
    if (!s) return;
    if (level !== undefined) s.level = level;
    if (pan !== undefined) { s.pan = pan; s.panner.pan.value = pan; }
    if (octave !== undefined) s.octave = octave;
    if (maxCm !== undefined) s.maxCm = maxCm;
    if (r0 !== undefined) s.r0 = r0;
    if (on !== undefined) s.on = on;
    s.gain.gain.setTargetAtTime(s.on ? s.level : 0, this.ctx.currentTime, 0.02);
    if (!s.on) this._hushStrip(s);
  }

  setWet(v) {
    this.params.wet = v;
    if (this._wet) this._wet.gain.setTargetAtTime(v, this.ctx.currentTime, 0.05);
  }

  /**
   * Targets mode: voice hardware-rule detections directly. `list` is
   * [[cm, over], ...] strongest first — no peak picking here, no gate, no
   * noise floor; a still wall is a steady tone. `over` (magnitude over the
   * vendor threshold, 1..~15) maps to loudness on a log2 curve so 2x over
   * the line is a clearly different volume than 8x.
   */
  playTargets(i, list) {
    const s = this.strips?.[i];
    if (!s || !s.on || s.level <= 0) return;
    if (!s.voices) this._makeVoices(s);
    const { fNear, fFar, glide, gamma } = this.params;
    const span = Math.max(s.maxCm - s.r0, 1e-9);
    const mul = Math.pow(2, s.octave);
    const t = this.ctx.currentTime;
    const used = new Set();

    const drive = (voice, cm, over) => {
      voice.bin = cm;                          // sticky key is cm here
      const pos = Math.min(1, Math.max(0, (cm - s.r0) / span));
      const f = fNear * Math.pow(fFar / fNear, pos) * mul;
      const a = Math.min(1, Math.log2(Math.max(over, 1)) / 3); // 8x over = full
      voice.osc.frequency.setTargetAtTime(f, t, glide);
      voice.osc2.frequency.setTargetAtTime(2 * f, t, glide);
      voice.g2.gain.setTargetAtTime(0.5 * (1 - pos) * (1 - pos), t, 0.03);
      voice.g.gain.setTargetAtTime(0.5 * Math.pow(a, gamma), t, 0.03);
    };

    // sticky pass: a voice follows the nearest target within 20 cm
    for (const voice of s.voices) {
      if (voice.bin < 0) continue;
      let best = -1, bestD = 20;
      list.forEach(([cm], j) => {
        const d = Math.abs(cm - voice.bin);
        if (!used.has(j) && d < bestD) { best = j; bestD = d; }
      });
      if (best >= 0) { used.add(best); drive(voice, list[best][0], list[best][1]); }
      else { voice.bin = -1; voice.g.gain.setTargetAtTime(0, t, 0.25); }
    }
    for (let j = 0; j < list.length; j++) {
      if (used.has(j)) continue;
      const free = s.voices.find((v) => v.bin < 0);
      if (!free) break;
      used.add(j);
      drive(free, list[j][0], list[j][1]);
    }
  }

  /** Voice one frame of one channel, whichever mode is active.
   * No `peak`: profiles arrive in sigmas and the scale is absolute. */
  playStrip(i, profile, seconds) {
    const s = this.strips?.[i];
    if (!s || !s.on || s.level <= 0) return;

    if (this.params.mode === "ping") {
      // Snapshot, deliberately. A ping covers ~15 frames at 19 Hz, so
      // combining them looks like free SNR — it is not. Measured on both
      // shipped (static) recordings, echoes voiced per ping:
      //     snapshot 0.25 scene / 0.47 empty     <- honest
      //     max-hold 2.41 scene / 3.47 empty     <- MORE on the empty file
      //     mean x sqrt(N) 7.37 / 7.32           <- fires equally on both
      // Every integrator inflates the empty control as much or more, because
      // the clutter residue is temporally correlated (lag-1 autocorrelation
      // 0.75), so averaging does not divide it by sqrt(N) while the rescale
      // multiplies it anyway. A quiet scene really does ping into silence;
      // that is the recording being honest, not the engine being broken.
      if (!s.lastProf || s.lastProf.length !== profile.length)
        s.lastProf = new Float32Array(profile.length);
      s.lastProf.set(profile);
    } else if (this.params.mode === "tones") {
      this._tones(s, profile);
    } else {
      this._sweep(s, profile, seconds);
    }
  }

  /** Silence everything that persists — call on pause / disconnect. */
  hush() {
    if (!this.ctx) return;
    for (const s of this.strips) this._hushStrip(s);
  }

  _hushStrip(s) {
    s.lastProf = null;          // stops the sonar from pinging a stale scene
    s.voices?.forEach((v) => {
      v.g.gain.setTargetAtTime(0, this.ctx.currentTime, 0.03);
      v.bin = -1;
    });
  }

  /* compressive loudness: x^gamma, gamma < 1 lifts weak echoes into
     audibility (x = 0.08 at gamma 0.5 -> 0.28, vs 0.014 under a dB map) */
  _amp(x) {
    if (x <= 0) return 0;
    return Math.pow(Math.min(1, x), this.params.gamma);
  }

  /** Local maxima above `thr`, outside the blind zone, deduped by minSep. */
  _peaks(prof, thr, blind, minSep, maxN) {
    const n = prof.length, cand = [];
    for (let i = Math.max(1, blind); i < n - 1; i++) {
      const v = prof[i];
      if (v > thr && v >= prof[i - 1] && v >= prof[i + 1]) cand.push([v, i]);
    }
    cand.sort((a, b) => b[0] - a[0]);
    const picked = [];
    for (const c of cand) {
      if (picked.every((p) => Math.abs(p[1] - c[1]) >= minSep)) picked.push(c);
      if (picked.length === maxN) break;
    }
    return picked;
  }

  /** blindCm is a position ON THE AXIS, whose origin is s.r0 (the RX
   * opens after the TX burst — 16.3 cm on the tx160 rig), not bin 0.
   * Mapping cm as a fraction of the buffer muted nearly double the label. */
  _blindBins(s, n) {
    const span = s.maxCm - s.r0;
    if (span <= 0) return 0;
    const bins = Math.ceil(((this.params.blindCm - s.r0) / span) * (n - 1));
    return Math.min(n, Math.max(0, bins));
  }

  /* ------------------------------------------------------------- ping -- */

  _schedulePing() {
    clearTimeout(this._pt);
    // Parking-sensor PRF: the slider sets the IDLE period; the nearest
    // voiced echo shortens it, down to 0.3x at point blank. Rhythm is the
    // one cue every transducer (and every juror) resolves perfectly.
    // Echo trains still stretch over pingS * 0.8, so accelerated pings
    // overlap only their silent far tails.
    const near = this._nearPos;
    const k = near === null || near === undefined ? 1 : 0.3 + 0.7 * near;
    this._pt = setTimeout(() => {
      try { this._pingAll(); } finally { this._schedulePing(); }
    }, this.params.pingS * 1000 * k);
  }

  _pingAll() {
    this._nearPos = null;
    if (!this.ctx || this.ctx.state !== "running" || this.params.mode !== "ping")
      return;
    for (const s of this.strips) {
      if (s.on && s.level > 0 && s.lastProf) this._ping(s);
    }
  }

  _ping(s) {
    const prof = s.lastProf;
    const n = prof.length;
    const { gate, pingS } = this.params;
    const gateAbs = gate;
    const blind = this._blindBins(s, n);

    // echoes spread over most of the period; the rest is silence to breathe
    const stretch = pingS * 0.8;
    const f0 = 1100 * Math.pow(2, s.octave);
    const wDur = 0.014, wTau = 0.0045;          // wavelet: short decaying sine
    const wN = Math.round(wDur * SR);
    const len = Math.round((0.03 + stretch) * SR) + wN + 1;
    const buf = this.ctx.createBuffer(1, len, SR);
    const out = buf.getChannelData(0);

    const addWavelet = (t0, amp, f) => {
      const o = Math.round(t0 * SR);
      for (let k = 0; k < wN && o + k < len; k++) {
        const t = k / SR;
        out[o + k] += amp * Math.sin(2 * Math.PI * f * t) * Math.exp(-t / wTau);
      }
    };

    // the emission tick — the listener's time reference, always audible
    addWavelet(0, 0.3, f0 * 2);

    // every distinct echo, not just the top few: the render is a snapshot,
    // so there is no frame-to-frame identity to keep stable here
    const scale = 1 / Math.max(FULL_SIGMA - gateAbs, 1e-9);
    for (const [v, i] of this._peaks(prof, gateAbs, blind, 3, 12)) {
      const pos = i / (n - 1);
      const a = this._amp((v - gateAbs) * scale);
      addWavelet(0.03 + pos * stretch, a, f0);
      // brightness: near echoes carry an octave partial (far = pure)
      addWavelet(0.03 + pos * stretch, a * 0.5 * (1 - pos) * (1 - pos), f0 * 2);
      if (this._nearPos === null || pos < this._nearPos) this._nearPos = pos;
    }

    const node = this.ctx.createBufferSource();
    node.buffer = buf;
    node.connect(s.gain);
    node.start();
  }

  /* ------------------------------------------------------------ tones -- */

  _makeVoices(s) {
    s.voices = [];
    for (let k = 0; k < VOICES; k++) {
      const osc = this.ctx.createOscillator();
      const g = this.ctx.createGain();
      g.gain.value = 0;
      osc.connect(g);
      g.connect(s.gain);
      osc.start();
      // brightness harmonic: an octave partial mixed in proportionally to
      // NEARNESS. Near = rich, far = pure sine. A lowpass can't do this on
      // sine voices (nothing above the carrier to cut), and sinking far
      // targets toward low frequencies would bury them on bone conduction.
      const osc2 = this.ctx.createOscillator();
      const g2 = this.ctx.createGain();
      g2.gain.value = 0;
      osc2.connect(g2);
      g2.connect(g);
      osc2.start();
      s.voices.push({ osc, g, osc2, g2, bin: -1 });
    }
  }

  _tones(s, prof) {
    if (!s.voices) this._makeVoices(s);

    const { fNear, fFar, gate, glide } = this.params;
    const n = prof.length;
    // hysteresis: born loud, survives quiet — a peak flickering at the gate
    // no longer toggles its voice at the frame rate
    const gateHi = gate * 1.5;
    const gateLo = gate * 0.75;
    const blind = this._blindBins(s, n);
    const minSep = Math.max(3, Math.round(n * 0.05));
    const maxJump = Math.round(n * 0.15);

    const cands = this._peaks(prof, gateLo, blind, minSep, 6);
    const t = this.ctx.currentTime;
    const mul = Math.pow(2, s.octave);
    const scale = 1 / Math.max(FULL_SIGMA - gateLo, 1e-9);
    const used = new Set();

    const drive = (voice, mag, bin) => {
      voice.bin = bin;
      const pos = bin / (n - 1);
      const f = fNear * Math.pow(fFar / fNear, pos) * mul;
      let amp = 0.5 * this._amp((mag - gateLo) * scale);
      // crude equal-loudness tilt: low carriers need more level to be heard
      amp *= Math.min(2, Math.pow(600 / f, 0.3));
      voice.osc.frequency.setTargetAtTime(f, t, glide);
      voice.osc2.frequency.setTargetAtTime(2 * f, t, glide);
      voice.g2.gain.setTargetAtTime(0.5 * (1 - pos) * (1 - pos), t, 0.03);
      voice.g.gain.setTargetAtTime(amp, t, 0.03);        // fast attack
    };

    // sticky pass: each active voice follows the nearest candidate
    for (const voice of s.voices) {
      if (voice.bin < 0) continue;
      let best = -1, bestD = maxJump + 1;
      cands.forEach((c, j) => {
        const d = Math.abs(c[1] - voice.bin);
        if (!used.has(j) && d < bestD) { best = j; bestD = d; }
      });
      if (best >= 0) { used.add(best); drive(voice, cands[best][0], cands[best][1]); }
      else { voice.bin = -1; voice.g.gain.setTargetAtTime(0, t, 0.25); } // slow release
    }
    // birth pass: strong new peaks claim silent voices
    for (let j = 0; j < cands.length; j++) {
      if (used.has(j) || cands[j][0] < gateHi) continue;
      const free = s.voices.find((v) => v.bin < 0);
      if (!free) break;
      used.add(j);
      drive(free, cands[j][0], cands[j][1]);
    }
  }

  /* ------------------------------------------------------------ sweep -- */

  _sweep(s, profile, seconds) {
    const n = Math.max(1, Math.round(seconds * SR));
    const buf = this.ctx.createBuffer(1, n, SR);
    const out = buf.getChannelData(0);
    const { fNear, fFar, sweep, gate, blindCm } = this.params;
    const mul = Math.pow(2, s.octave);
    const gateAbs = gate;
    const scale = 1 / Math.max(FULL_SIGMA - gateAbs, 1e-9);
    const span = s.maxCm - s.r0;
    const blindFrac = span > 0 ? Math.max(0, (blindCm - s.r0) / span) : 0;

    let phase = s.phase;
    const src = profile.length;
    for (let k = 0; k < n; k++) {
      const pos = k / n;
      const x = pos * (src - 1);
      const i0 = x | 0;
      const frac = x - i0;
      const a = profile[i0], b = profile[Math.min(i0 + 1, src - 1)];
      const m = a + (b - a) * frac;
      const env = (pos < blindFrac || m <= gateAbs)
        ? 0
        : this._amp((m - gateAbs) * scale);
      const freq = (sweep ? fNear + (fFar - fNear) * pos : fNear) * mul;
      phase += (2 * Math.PI * freq) / SR;
      out[k] = env * Math.sin(phase);
    }
    s.phase = phase % (2 * Math.PI);

    const node = this.ctx.createBufferSource();
    node.buffer = buf;
    node.connect(s.gain);
    node.start();
  }

  /* ------------------------------------------------------------- misc -- */

  setGain(v) {
    this.params.gain = v;
    // setTargetAtTime, not .value: a dragged slider fires continuously and
    // stepping the gain is audible as zipper noise.
    if (this.master) this.master.gain.setTargetAtTime(v, this.ctx.currentTime, 0.02);
  }

  /** Live spectrum for the visualiser, 0..1 per bin. */
  spectrum() {
    if (!this.analyser) return null;
    this.analyser.getByteFrequencyData(this._freqBins);
    return this._freqBins;
  }

  get sampleRate() { return this.ctx ? this.ctx.sampleRate : SR; }

}
