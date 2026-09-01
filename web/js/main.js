/**
 * Wiring: data source -> audio graph + canvases.
 *
 * One rAF loop drives everything. It decides how many sensor frames are due
 * from wall-clock time rather than assuming one frame per animation tick — the
 * sensor runs at 25–39 Hz and the display at 60, so those two must not be
 * locked together.
 */

import { Session, FULL_SIGMA } from "./data.js";
import { EchoAudio } from "./audio.js";
import { AScan, Waterfall, Spectrum, ChannelGrid } from "./scope.js";
import { LiveBridge } from "./bridge.js";

const $ = (id) => document.getElementById(id);

const state = {
  session: null,
  audio: new EchoAudio(),
  playing: false,
  frame: 0,
  t0: 0,
  rafId: 0,
  ears: [0, 0],
  bridge: null,
  live: false,
  meta: null,      // whichever source is active: {channels, nSamples, rangeCm}
};

const views = {};
let bufs = [];     // one scratch profile per channel

function setStatus(msg, kind = "") {
  for (const id of ["status", "status2"]) {
    const el = $(id);
    if (!el) continue;
    el.textContent = msg;
    // status2 must KEEP .meta (mono/size/margin) — replacing it made the
    // mirror render unstyled and reflow the row on every ok/err change
    el.className = id === "status2" ? `meta ${kind}`.trim() : kind;
  }
}

/* ---------------------------------------------------------------- mixer -- */

/**
 * Build one strip per channel and hand the defaults to the audio graph.
 *
 * Defaults: the two pulse-echo channels are the instrument — on, hard-panned
 * left/right, that is the binaural mapping. The pitch-catch channels are off
 * and an octave down; they exist so a cross-echo can be checked against the
 * PE pair while tuning, not to be a third voice.
 */
/** Blind zone that fits the data: the physical 18 cm (TX overlap) for the
 * long-range rig, but never more than a quarter of a short recording's axis —
 * 18 cm of mute on a 22 cm file silenced almost the whole demo. */
function fitBlind(meta) {
  // Only bound the slider to the axis; do NOT choose a value. Per-bin
  // normalisation already flattens the ringdown (measured: near-field
  // residual 1.6-2.0 sigma p95, 0.00% over the gate, same as the far
  // field), so muting the near bins by default only hid close objects —
  // exactly the ones a wearable most needs. Left at 0 unless the user
  // asks for it.
  const ax = meta.rangeCm[state.ears[0]] || meta.rangeCm[0];
  $("blind").min = "0";
  $("blind").max = String(Math.round(ax[0] + (ax.at(-1) - ax[0]) * 0.25));
}

function buildMixer(meta) {
  const host = $("mixer");
  host.textContent = "";
  state.audio.ensureStrips(meta.channels.length);
  const [l, r] = state.ears;

  meta.channels.forEach(([tx, rx], i) => {
    const isPE = tx === rx;
    const isEar = i === l || i === r;
    const cfg = isEar
      ? { on: true, level: 0.9, pan: i === l ? -1 : 1, octave: 0 }
      : { on: false, level: 0.35, pan: 0, octave: isPE ? 0 : -1 };
    cfg.maxCm = meta.rangeCm[i].at(-1);   // blind zone is set in axis cm
    cfg.r0 = meta.rangeCm[i][0];          // axis origin (RX opens post-burst)
    state.audio.setStrip(i, cfg);

    const el = document.createElement("div");
    el.className = `strip ${isPE ? "pe" : "pc"}`;
    el.innerHTML = `
      <label class="sw"><input type="checkbox" ${cfg.on ? "checked" : ""}>
        <b>${tx}→${rx}</b> ${isPE ? "PE" : "PC"}</label>
      <label>Vol <input type="range" min="0" max="1" step="0.01" value="${cfg.level}"></label>
      <label>Pan <input type="range" min="-1" max="1" step="0.05" value="${cfg.pan}"></label>
      <label>Oct (freq ×2ⁿ) <select>
        <option value="-2">−2</option><option value="-1">−1</option>
        <option value="0">0</option><option value="1">+1</option>
      </select></label>`;
    const [sw, level, pan] = el.querySelectorAll("input");
    const oct = el.querySelector("select");
    oct.value = String(cfg.octave);
    const push = () => state.audio.setStrip(i, {
      on: sw.checked, level: +level.value, pan: +pan.value, octave: +oct.value,
    });
    el.addEventListener("input", push);
    host.appendChild(el);
  });
}

/* ---------------------------------------------------------------- data --- */

/** The raw dataset is a deliberate counter-example; say so loudly, and stop
 * saying it the moment the source is no longer raw — including on a live
 * connect and on a failed load, which both used to leave it on screen. */
function setRawWarn(raw) {
  $("rawWarn").hidden = !raw;
  $("modeHint").hidden = raw;
}

/* Per-dataset suggested playback settings.

   A dataset's meta may carry `suggest`, e.g. {mode, gate, gamma}: presets
   tuned for THAT recording (the palm sweep wants a high gate so the
   cross-bleed ear falls silent and the sound truly shuttles). Applied on
   load; datasets without one restore the page defaults, so one dataset's
   tuning never leaks into the next. Presentation only — the data itself
   is untouched. */
const SUGGEST_SLIDERS = ["gain", "gamma", "gate", "blind", "ping", "wet",
                         "fNear", "fFar"];

function currentSettings() {
  const out = { mode: $("mode").value, sweep: $("sweep").checked };
  for (const id of SUGGEST_SLIDERS) out[id] = $(id).value;
  return out;
}

function applySettings(s) {
  for (const id of SUGGEST_SLIDERS) {
    if (s[id] === undefined) continue;
    const el = $(id);
    el.value = String(s[id]);
    el.dispatchEvent(new Event("input"));      // runs the bind() sync
  }
  if (s.mode !== undefined && $("mode").value !== s.mode) {
    $("mode").value = s.mode;
    $("mode").dispatchEvent(new Event("change"));
  }
  if (s.sweep !== undefined) {
    $("sweep").checked = !!s.sweep;
    $("sweep").dispatchEvent(new Event("change"));
  }
}

function applyPreset(suggest) {
  if (!state.baseline) return;                 // boot not finished yet
  applySettings(suggest ? { ...state.baseline, ...suggest }
                        : state.baseline);
}

async function loadSession(stem) {
  if (state.live) toggleLive();   // one source at a time
  const wasPlaying = state.playing;
  stop();
  setStatus(`Loading ${stem} …`);
  try {
    const s = await Session.load(stem);
    state.session = s;
    state.frame = 0;
    // The two "ears" are the pulse-echo channels: tx === rx, one per sensor.
    const pe = s.pulseEcho;
    // exporter records which sensor is on which temple; id order mirrors L/R
    state.ears = s.meta.ears?.length === 2 ? s.meta.ears
      : pe.length >= 2 ? [pe[0], pe[pe.length - 1]] : [0, 0];
    state.meta = s.meta;
    bufs = Array.from({ length: s.nChannels }, () => new Float32Array(s.nSamples));
    views.grid.reset();
    buildMixer(s.meta);
    fitBlind(s.meta);

    setRawWarn(!s.sigmaUnits);
    applyPreset(s.meta.suggest);
    $("meta").textContent =
      `${s.meta.title} · ${s.nFrames} frames @ ${s.frameHz.toFixed(1)} Hz · ` +
      `${s.nChannels} ch × ${s.nSamples} samples · ` +
      `${s.rangeCm(state.ears[0])[0].toFixed(0)}–` +
      `${s.rangeCm(state.ears[0]).at(-1).toFixed(0)} cm` +
      (s.meta.staticRemoved ? " · static clutter removed" : " · raw counts");
    setStatus("Ready — headphones on, press Play", "ok");
    render(0);
    if (wasPlaying) play();       // the raw/normalised A/B is a comparison,
                                  // and stopping between halves kills it
  } catch (e) {
    setRawWarn(false);
    setStatus(location.protocol === "file:"
      ? "Needs a local server (any static server will do) — run/8_web.py "
        + "· needs a local server"
      : `Load failed: ${e.message}`, "err");
  }
}

/* --------------------------------------------------------------- render -- */

function profilesAt(frame) {
  const s = state.session;
  return bufs.map((b, c) => s.profile(frame, c, b));
}

/** The two hard-panned pulse-echo channels, for the head-centred views. */
const earProfiles = (profs) => [profs[state.ears[0]], profs[state.ears[1]]];

function render(frame) {
  const s = state.session;
  if (!s) return;
  const profs = profilesAt(frame);
  const peak = FULL_SIGMA;
  const tgt = state.audio.params.mode === "targets"
    ? state.ears.map((c) => s.targetsAt(frame, c)) : null;
  views.ascan.draw(earProfiles(profs), s.rangeCm(state.ears[0]), peak,
                   state.audio.params, tgt);
  views.grid.draw(profs, state.meta, peak, state.audio.params.gate);
  views.spectrum.draw(state.audio.spectrum(), state.audio.sampleRate);

  const pl = s.peakOf(frame, state.ears[0]);
  const pr = s.peakOf(frame, state.ears[1]);
  $("roFrame").textContent = `${frame + 1} / ${s.nFrames}`;
  if (state.audio.params.mode === "targets") {
    const fmt = (list) => list?.length
      ? `${list[0][0].toFixed(0)} cm · ${list[0][1].toFixed(1)}×`
      : "—";
    $("roLeft").textContent = fmt(s.targetsAt(frame, state.ears[0]));
    $("roRight").textContent = fmt(s.targetsAt(frame, state.ears[1]));
    $("roLeft").classList.remove("dim");
    $("roRight").classList.remove("dim");
    return profs;
  }
  const readout = (el, p) => {
    const on = p.mag > state.audio.params.gate;
    el.textContent = `${p.cm.toFixed(0)} cm · ${p.mag.toFixed(1)} σ`;
    el.classList.toggle("dim", !on);   // below gate: shown, but not "found"
  };
  readout($("roLeft"), pl);
  readout($("roRight"), pr);
  return profs;
}

function loop() {
  if (!state.playing) return;
  const s = state.session;
  if (!s) return stop();
  const hz = s.frameHz * parseFloat($("speed").value);
  const due = Math.floor((performance.now() - state.t0) / 1000 * hz);

  if (due > state.frame) {
    // If the tab was backgrounded we can be many frames behind; render the
    // newest and voice only the last few, rather than blasting a burst.
    const jump = Math.min(due - state.frame, 3);
    for (let k = 0; k < jump; k++) {
      state.frame = (state.frame + 1) % s.nFrames;
      const profs = render(state.frame);
      const seconds = 1 / hz;
      if (state.audio.params.mode === "targets") {
        for (let c = 0; c < s.nChannels; c++)
          state.audio.playTargets(c, s.targetsAt(state.frame, c));
      } else {
        profs.forEach((p, c) => state.audio.playStrip(c, p, seconds));
      }
      views.waterfall.push(earProfiles(profs), FULL_SIGMA, state.audio.params.gate);
    }
    if (due - state.frame > 30) rebase();   // backgrounded tab came back
  } else {
    views.spectrum.draw(state.audio.spectrum(), state.audio.sampleRate);
  }
  state.rafId = requestAnimationFrame(loop);
}

/**
 * Autoplay insurance: if the browser left the AudioContext suspended in
 * spite of the button click, say so and resume on the next real gesture.
 */
function armResume() {
  const ctx = state.audio.ctx;
  if (!ctx || ctx.state === "running" || state.resumeArmed) return;
  state.resumeArmed = true;
  setStatus("Browser blocked audio — click anywhere to enable", "err");
  document.addEventListener("pointerdown", () => {
    state.audio.ctx?.resume();
    if ($("status").textContent.includes("blocked audio"))
      setStatus("Audio enabled", "ok");
  }, { once: true });
}

/* -------------------------------------------------------------- control -- */

/** One rebase for all three callers: t0 such that `due` lands exactly on
 * the current frame at the current speed. Rebasing to bare now() made due
 * restart at 0 and froze playback until the wall clock caught up. */
function rebase() {
  const s = state.session;
  if (!s) return;
  const hz = s.frameHz * parseFloat($("speed").value);
  state.t0 = performance.now() - (state.frame / hz) * 1000;
}

function play() {
  if (!state.session || state.playing) return;
  state.audio.ensure();            // must happen inside the click handler
  armResume();
  // The first buildMixer ran before any click, when there was no
  // AudioContext yet — its ensureStrips was a no-op and every channel
  // strip silently didn't exist. Materialize them now FROM THE DOM, so
  // slider moves made before the first Play are honoured, not wiped.
  if (state.meta && state.audio.strips.length === 0) {
    state.audio.ensureStrips(state.meta.channels.length);
    document.querySelectorAll("#mixer .strip").forEach((el, i) => {
      const [sw, level, pan] = el.querySelectorAll("input");
      state.audio.setStrip(i, {
        on: sw.checked, level: +level.value, pan: +pan.value,
        octave: +el.querySelector("select").value,
        maxCm: state.meta.rangeCm[i].at(-1), r0: state.meta.rangeCm[i][0],
      });
    });
  }
  state.audio.setGain(parseFloat($("gain").value));
  state.playing = true;
  rebase();
  $("play").textContent = "⏸ Pause";
  $("play").classList.add("on");
  cancelAnimationFrame(state.rafId);
  state.rafId = requestAnimationFrame(loop);
}

function stop() {
  state.playing = false;
  state.audio.hush();          // tone voices persist — silence them
  cancelAnimationFrame(state.rafId);
  const b = $("play");
  if (b) { b.textContent = "▶ Play"; b.classList.remove("on"); }
}

/* ----------------------------------------------------------------- live -- */

const syncD = () => window.__eeSync?.();

function toggleLive() {
  if (state.live) {
    state.bridge?.close();
    state.audio.hush();
    state.live = false;
    syncD();
    $("liveBtn").classList.remove("on");
    $("liveBtn").textContent = "🔌 Live";
    setStatus("Live disconnected");
    return;
  }
  stop();
  state.audio.ensure();
  armResume();
  state.bridge = new LiveBridge($("wsUrl").value.trim(), {
    onMeta: (meta) => {
      stop();                    // replay loop must not outlive its session
      state.session = null;
      state.meta = meta;
      $("meta").textContent =
        `Live · ${meta.nChannels} ch × ${meta.nSamples} samples · ` +
        `${meta.frameHz.toFixed(1)} Hz · ` +
        `${meta.rangeCm[0][0].toFixed(0)}–${meta.rangeCm[0].at(-1).toFixed(0)} cm`;
      state.liveMeta = meta;
      // the bridge knows which sensor is physically left; trust it over
      // channel order, and fall back to the first/last pulse-echo channel.
      state.ears = meta.ears?.length === 2 ? meta.ears
        : meta.pulseEcho.length >= 2
          ? [meta.pulseEcho[0], meta.pulseEcho.at(-1)] : [0, 0];
      views.grid.reset();
      setRawWarn(false);          // live is always sigma units
      buildMixer(meta);
      fitBlind(meta);
      syncD();
      setStatus("Live stream connected", "ok");
    },
    onFrame: (profiles, tg) => {
      const peak = FULL_SIGMA;
      const hz = state.liveMeta?.frameHz || 20;
      if (state.audio.params.mode === "targets") {
        profiles.forEach((_, c) => state.audio.playTargets(c, tg?.[c] ?? []));
      } else {
        profiles.forEach((p, c) => state.audio.playStrip(c, p, 1 / hz));
      }
      state.lastTargets = tg;
      const ears = earProfiles(profiles);
      const tgt = state.audio.params.mode === "targets"
        ? state.ears.map((c) => tg?.[c] ?? []) : null;
      views.ascan.draw(ears, state.liveMeta.rangeCm[state.ears[0]], peak,
                       state.audio.params, tgt);
      views.grid.draw(profiles, state.meta, peak, state.audio.params.gate);
      views.waterfall.push(ears, peak, state.audio.params.gate);
      views.spectrum.draw(state.audio.spectrum(), state.audio.sampleRate);
    },
    onWait: (msg) => setStatus(msg),
    onError: (msg) => {
      stop();
      state.audio.hush();          // or the ping timer voices the frozen
      setStatus(`Live connect failed: ${msg} — is the bridge running?`, "err");
      state.live = false;
      $("liveBtn").classList.remove("on");
      $("liveBtn").textContent = "🔌 Live";
    },
  });
  $("liveBtn").classList.add("on");
  $("liveBtn").textContent = "⏹ Disconnect";
  setStatus("Connecting to the bridge …");
  state.live = true;
  syncD();
}

/* ----------------------------------------------------------------- boot -- */

function boot() {
  views.ascan = new AScan($("ascan"));
  views.grid = new ChannelGrid($("grid"));
  views.waterfall = new Waterfall($("waterfall"));
  views.spectrum = new Spectrum($("spectrum"));

  $("play").addEventListener("click", () => (state.playing ? stop() : play()));
  $("liveBtn").addEventListener("click", toggleLive);
  $("dataset").addEventListener("change", (e) => loadSession(e.target.value));

  const bind = (id, fmt, apply) => {
    const el = $(id);
    const sync = () => { $(id + "V").textContent = fmt(el.value); apply(el.value); };
    el.addEventListener("input", sync);
    sync();
  };
  bind("gain", (v) => (+v).toFixed(2), (v) => state.audio.setGain(+v));
  bind("speed", (v) => `${(+v).toFixed(2)}×`, () => {
    if (state.playing) rebase();
  });
  bind("fNear", (v) => `${v} Hz`, (v) => (state.audio.params.fNear = +v));
  bind("fFar", (v) => `${v} Hz`, (v) => (state.audio.params.fFar = +v));
  bind("gamma", (v) => (+v).toFixed(2), (v) => (state.audio.params.gamma = +v));
  bind("gate", (v) => `${(+v).toFixed(1)} σ`, (v) => (state.audio.params.gate = +v));
  bind("blind", (v) => `${v} cm`, (v) => (state.audio.params.blindCm = +v));
  bind("ping", (v) => `${(+v).toFixed(1)} s`, (v) => (state.audio.params.pingS = +v));
  bind("wet", (v) => (+v).toFixed(2), (v) => state.audio.setWet(+v));
  const syncDisabled = window.__eeSync = () => {
    const m = state.audio.params.mode;
    // only once frames are actually arriving — a 40 s connect attempt must
    // not disable the one button that works without hardware
    const streaming = state.live && !!state.liveMeta;
    $("play").disabled = streaming;
    $("speed").disabled = streaming;
    // ping's carrier is fixed; pitch controls only drive tones/sweep/targets
    for (const id of ["fNear", "fFar"]) $(id).disabled = m === "ping";
    $("sweep").disabled = m !== "sweep";
    $("ping").disabled = m !== "ping";
    // targets mode ignores the sigma gate and the blind zone entirely —
    // its threshold is the vendor curve, its blind zone the ringdown region
    $("gate").disabled = m === "targets";
    $("blind").disabled = m === "targets";
    $("wet").disabled = false;
  };
  $("mode").addEventListener("change", (e) => {
    state.audio.params.mode = e.target.value;
    state.audio.hush();        // don't let the other engine's tail ring on
    syncDisabled();
  });
  syncDisabled();
  $("sweep").addEventListener("change", (e) => {
    state.audio.params.sweep = e.target.checked;
  });

  window.addEventListener("resize", () => state.session && render(state.frame));
  state.baseline = currentSettings();          // page defaults, for datasets
                                               // without a suggest block
  loadSession($("dataset").value);
  // console handle for live tuning: EE.audio.params, EE.audio.strips, ...
  window.EE = state;
}

boot();
