/**
 * Canvas views. All of them are DPR-aware and redraw only from
 * requestAnimationFrame — nothing here schedules its own timer.
 *
 *   AScan     magnitude vs distance, one trace per ear, mirrored so the left
 *             ear runs leftwards from the centre (that is where the sensor is)
 *   Waterfall time x distance, scrolling — the history the ear cannot hold
 *   Spectrum  AnalyserNode output, i.e. what is actually reaching the speakers
 */

function fitDPR(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  // round: at fractional DPR (Windows 125%) the exact compare never matches
  // and the backing store reallocs+clears on every single frame
  const W = Math.round(w * dpr), H = Math.round(h * dpr);
  if (canvas.width !== W || canvas.height !== H) {
    canvas.width = W;
    canvas.height = H;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

const L_COLOR = "#4ea8ff";
const R_COLOR = "#ff9d4e";

/** Height for a value in noise sigmas, 0..1.
 *
 * Everything is normalised per bin now, so the noise floor sits at a
 * CONSTANT ~1.8 sigma across the whole range — and the old sqrt(s/full)
 * mapping drew that at 47% of full height, i.e. a wall of grass from one
 * end of the axis to the other with the real peaks barely above it. Worse,
 * the audio was gating at 3.5 sigma while the display drew from zero, so
 * the picture and the sound disagreed about what counted as a target.
 *
 * Below the gate: a low carpet, linear, capped at FLOOR_H — visible, so you
 * can see the noise and judge the gate, but never mistakable for signal.
 * Above it: the same sqrt curve the ear gets, over the remaining height.
 */
const FLOOR_H = 0.15;
function heightOf(sigma, gate, full) {
  if (!(full > gate)) return 0;
  if (sigma <= gate) return FLOOR_H * Math.max(0, sigma) / Math.max(gate, 1e-9);
  const v = Math.min(1, (sigma - gate) / (full - gate));
  return FLOOR_H + (1 - FLOOR_H) * Math.sqrt(v);
}

/** Head-centred A-scan: left ear grows leftward, right ear rightward. */
export class AScan {
  constructor(canvas) { this.canvas = canvas; }

  /** `targets` (optional) is [[cm, over], ...] per ear, from the hardware
   * rule. Drawn as standing markers because they come from RAW counts: they
   * survive an object holding still, which the clutter-removed trace behind
   * them does NOT — a hand held steady fades out of that trace with a 2.6 s
   * time constant. Without this the Targets mode was audible but invisible. */
  draw(profiles, rangeCm, peak, params, targets) {
    const { ctx, w, h } = fitDPR(this.canvas);
    ctx.clearRect(0, 0, w, h);
    const mid = w / 2;
    // the axis has an origin: RX opens after the TX burst, so bin 0 is
    // rangeCm[0] (16.3 cm on the tx160 rig), not zero. Rings placed as
    // cm/maxCm disagreed with the trace by that offset.
    const r0 = rangeCm[0];
    const maxCm = rangeCm[rangeCm.length - 1];
    const span = maxCm - r0;

    // distance rings every 20 cm
    ctx.strokeStyle = "rgba(255,255,255,.08)";
    ctx.fillStyle = "rgba(255,255,255,.32)";
    ctx.font = "10px ui-monospace, monospace";
    ctx.textAlign = "center";
    ctx.lineWidth = 1;
    const ring = maxCm > 120 ? 50 : maxCm > 60 ? 20 : maxCm > 25 ? 10 : 5;
    for (let cm = Math.ceil(r0 / ring) * ring; cm <= maxCm; cm += ring) {
      const dx = ((cm - r0) / span) * (mid - 10);
      for (const x of [mid - dx, mid + dx]) {
        ctx.beginPath(); ctx.moveTo(x, 14); ctx.lineTo(x, h); ctx.stroke();
      }
      const lbl = cm === Math.ceil(r0 / ring) * ring ? `${cm} cm` : `${cm}`;
      ctx.fillText(lbl, mid + dx, 11);
      ctx.fillText(lbl, mid - dx, 11);
    }
    // the head
    ctx.fillStyle = "rgba(255,255,255,.5)";
    ctx.fillText("YOU 你", mid, h - 4);

    // tuning overlays: what the gate and blind-zone sliders actually do.
    // Tuning was ear-only before — the sliders had no visual consequence.
    if (params) {
      const bw = Math.max(0, ((params.blindCm - r0) / span)) * (mid - 10);
      if (bw > 0) {
        ctx.fillStyle = "rgba(255,107,107,.10)";
        ctx.fillRect(mid - bw, 14, bw * 2, h - 14);
        // a hard edge, always: at the default the shaded band is ~5 px wide
        // and the caption was ten times wider than the thing it labelled
        ctx.strokeStyle = "rgba(255,107,107,.45)";
        ctx.beginPath();
        for (const x of [mid - bw, mid + bw]) { ctx.moveTo(x, 14); ctx.lineTo(x, h); }
        ctx.stroke();
        if (bw > 30) {
          ctx.fillStyle = "rgba(255,107,107,.5)";
          ctx.font = "9px ui-monospace, monospace";
          ctx.textAlign = "center";
          ctx.fillText("blind 盲区", mid, 24);
        }
      }
      // gate is an absolute sigma now, and `peak` is the sigma full scale,
      // so the line is exactly where the audio actually cuts
      const gy = h - 12 - FLOOR_H * (h - 30);   // exactly where signal starts
      ctx.strokeStyle = "rgba(255,107,107,.35)";
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(10, gy); ctx.lineTo(w - 10, gy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(255,107,107,.5)";
      ctx.textAlign = "left";
      ctx.font = "9px ui-monospace, monospace";
      ctx.fillText("gate", 12, gy - 3);
    }

    const gate = params ? params.gate : 0;
    profiles.forEach((prof, ear) => {
      const dir = ear === 0 ? -1 : 1;
      ctx.strokeStyle = ear === 0 ? L_COLOR : R_COLOR;
      ctx.fillStyle = ear === 0 ? "rgba(78,168,255,.16)" : "rgba(255,157,78,.16)";
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(mid, h - 12);
      for (let i = 0; i < prof.length; i++) {
        const x = mid + dir * (i / (prof.length - 1)) * (mid - 10);
        ctx.lineTo(x, h - 12 - heightOf(prof[i], gate, peak) * (h - 30));
      }
      ctx.lineTo(mid + dir * (mid - 10), h - 12);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    });

    if (!targets) return;
    ctx.font = "10px ui-monospace, monospace";
    targets.forEach((list, ear) => {
      if (!list) return;
      const dir = ear === 0 ? -1 : 1;
      list.forEach(([cm, over], k) => {
        const x = mid + dir * Math.min(1, (cm - r0) / span) * (mid - 10);
        const hh = Math.min(1, Math.log2(Math.max(over, 1)) / 3) * (h - 40);
        ctx.strokeStyle = ear === 0 ? L_COLOR : R_COLOR;
        ctx.lineWidth = 2.5;
        ctx.globalAlpha = 0.9;
        ctx.beginPath();
        ctx.moveTo(x, h - 12);
        ctx.lineTo(x, h - 16 - hh);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(x, h - 18 - hh, 3, 0, 2 * Math.PI);
        ctx.fillStyle = ear === 0 ? L_COLOR : R_COLOR;
        ctx.fill();
        ctx.globalAlpha = 1;
        if (k === 0) {
          ctx.textAlign = dir < 0 ? "right" : "left";
          ctx.fillText(`${cm.toFixed(0)}cm ${over.toFixed(1)}×`,
                       x + dir * 6, h - 22 - hh);
        }
      });
    });
  }
}

/** Scrolling time x distance history. */
export class Waterfall {
  constructor(canvas) {
    this.canvas = canvas;
    this.off = document.createElement("canvas");
    this.col = 0;
  }

  push(profiles, peak, gate = 0) {
    const { w, h } = fitDPR(this.canvas);
    if (this.off.width !== w || this.off.height !== h) {
      this.off.width = w; this.off.height = h; this.col = 0;
    }
    const octx = this.off.getContext("2d");
    const half = h / 2;

    profiles.forEach((prof, ear) => {
      const y0 = ear === 0 ? 0 : half;
      for (let y = 0; y < half; y++) {
        const i = Math.floor((y / half) * prof.length);
        const s = heightOf(prof[i], gate, peak);
        // blue for the left ear, orange for the right — same key as the A-scan
        octx.fillStyle = ear === 0
          ? `rgba(${40 + 60 * s | 0},${120 * s + 40 | 0},${255 * s | 0},1)`
          : `rgba(${255 * s | 0},${140 * s + 30 | 0},${40 * s | 0},1)`;
        octx.fillRect(this.col, y0 + y, 2, 1);
      }
    });
    this.col = (this.col + 2) % w;
    // clear a gap ahead of the write head so the seam is legible (wrapping)
    const gapEnd = Math.min(this.col + 12, w);
    octx.clearRect(this.col, 0, gapEnd - this.col, h);
    if (this.col + 12 > w) octx.clearRect(0, 0, this.col + 12 - w, h);

    const { ctx } = fitDPR(this.canvas);
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(this.off, 0, 0);
    ctx.strokeStyle = "rgba(255,255,255,.25)";
    ctx.beginPath(); ctx.moveTo(this.col, 0); ctx.lineTo(this.col, h); ctx.stroke();
  }
}

/** What the speakers are actually getting, straight off the AnalyserNode. */
export class Spectrum {
  constructor(canvas) { this.canvas = canvas; }

  draw(bins, sampleRate) {
    const { ctx, w, h } = fitDPR(this.canvas);
    ctx.clearRect(0, 0, w, h);
    if (!bins) return;
    // only the bottom ~4 kHz is ever occupied — the carrier lives at 300–1800 Hz
    const nyquist = sampleRate / 2;
    const show = Math.min(bins.length, Math.floor((4000 / nyquist) * bins.length));
    const bw = w / show;
    const g = ctx.createLinearGradient(0, h, 0, 0);
    g.addColorStop(0, "#2d5a8a");
    g.addColorStop(1, "#7ec8ff");
    ctx.fillStyle = g;
    for (let i = 0; i < show; i++) {
      const v = bins[i] / 255;
      ctx.fillRect(i * bw, h - v * h, Math.max(1, bw - 0.5), v * h);
    }
    ctx.fillStyle = "rgba(255,255,255,.3)";
    ctx.font = "10px ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.fillText("0", 2, h - 3);
    ctx.textAlign = "right";
    ctx.fillText("4 kHz", w - 2, h - 3);
  }
}

/**
 * 2x2 (or NxN) channel grid — one A-scan per (tx, rx) pair.
 *
 * Row = TX, column = RX, so the diagonal is pulse-echo and is shaded. This is
 * the tuning view: it shows every channel raw, including the two pitch-catch
 * channels that the ear mix may have turned down to nothing.
 *
 * A faint max-hold trace persists per channel so a brief echo does not vanish
 * before you have looked at it.
 */
export class ChannelGrid {
  constructor(canvas) {
    this.canvas = canvas;
    this.hold = null;     // per-channel max-hold, decayed each frame
    this.peakBin = null;
  }

  /** Session switches with identical shape must not inherit ghost traces —
   * the previous scene lingered ~6 s on the new one's grid. */
  reset() { this.hold = null; }

  draw(profiles, meta, peak, gate = 0) {
    const { ctx, w, h } = fitDPR(this.canvas);
    ctx.clearRect(0, 0, w, h);
    const chans = meta.channels;
    // rows and columns are derived separately: a queue that transmits from one
    // sensor only is not square, and a shared id list would drop its cells.
    const txs = [...new Set(chans.map((c) => c[0]))].sort((a, b) => a - b);
    const rxs = [...new Set(chans.map((c) => c[1]))].sort((a, b) => a - b);
    if (!txs.length || !rxs.length) return;

    if (!this.hold || this.hold.length !== chans.length ||
        this.hold[0].length !== meta.nSamples) {
      this.hold = chans.map(() => new Float32Array(meta.nSamples));
      this.peakBin = chans.map(() => 0);
    }

    const pad = 26, gap = 6;
    const cw = (w - pad - gap * (rxs.length - 1)) / rxs.length;
    const chh = (h - pad - gap * (txs.length - 1)) / txs.length;

    ctx.font = "9px ui-monospace, monospace";

    chans.forEach((c, k) => {
      const [tx, rx] = c;
      const row = txs.indexOf(tx), col = rxs.indexOf(rx);
      if (row < 0 || col < 0) return;
      const x0 = pad + col * (cw + gap);
      const y0 = pad + row * (chh + gap);
      const isPE = tx === rx;
      const prof = profiles[k];

      // cell
      ctx.fillStyle = isPE ? "rgba(78,168,255,.055)" : "rgba(255,255,255,.022)";
      ctx.fillRect(x0, y0, cw, chh);
      ctx.strokeStyle = "rgba(120,160,220,.16)";
      ctx.lineWidth = 1;
      ctx.strokeRect(x0 + .5, y0 + .5, cw - 1, chh - 1);

      if (!prof) return;
      const hold = this.hold[k];
      let bestV = 0, bestI = 0;

      // max-hold decays so it tracks rather than saturating
      const trace = (arr, style, width) => {
        ctx.strokeStyle = style; ctx.lineWidth = width;
        ctx.beginPath();
        for (let i = 0; i < arr.length; i++) {
          const x = x0 + (i / (arr.length - 1)) * cw;
          const y = y0 + chh - 2 - heightOf(arr[i], gate, peak) * (chh - 12);
          i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
        }
        ctx.stroke();
      };

      for (let i = 0; i < prof.length; i++) {
        hold[i] = Math.max(hold[i] * 0.97, prof[i]);
        if (prof[i] > bestV) { bestV = prof[i]; bestI = i; }
      }
      trace(hold, "rgba(255,255,255,.16)", 1);
      trace(prof, isPE ? "#4ea8ff" : "#ff9d4e", 1.4);

      // peak marker + label
      const label = `${tx}→${rx}${isPE ? " PE" : " PC"}`;
      ctx.fillStyle = isPE ? "rgba(78,168,255,.85)" : "rgba(255,157,78,.85)";
      ctx.textAlign = "left";
      ctx.fillText(label, x0 + 4, y0 + 11);
      if (bestV > peak * 0.03) {
        const cm = meta.rangeCm[k][bestI];
        const px = x0 + (bestI / (prof.length - 1)) * cw;
        ctx.strokeStyle = "rgba(255,255,255,.4)";
        ctx.beginPath(); ctx.moveTo(px, y0 + 14); ctx.lineTo(px, y0 + chh - 2); ctx.stroke();
        ctx.textAlign = "right";
        ctx.fillStyle = "rgba(255,255,255,.62)";
        ctx.fillText(`${cm.toFixed(0)}cm`, x0 + cw - 4, y0 + 11);
      }
    });

    // axis labels: rows are TX, columns are RX
    ctx.fillStyle = "rgba(232,238,251,.4)";
    ctx.textAlign = "center";
    rxs.forEach((id, i) => ctx.fillText(`RX ${id}`, pad + i * (cw + gap) + cw / 2, 12));
    txs.forEach((id, i) => {
      ctx.save();
      ctx.translate(11, pad + i * (chh + gap) + chh / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(`TX ${id}`, 0, 0);
      ctx.restore();
    });
  }
}
