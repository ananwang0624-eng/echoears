/**
 * Loads a session packed by tools/export_web.py. The decode must mirror the
 * encoder exactly.
 *
 * units "sigma" (default): values are per-bin noise sigmas and the quantiser
 * is linear, `sigma = code * sigmaPerCode`. Raw magnitudes span ~70 dB across
 * the range axis, so a single gate or loudness curve cannot serve both the
 * 20 cm ringdown and a 2 m wall; in sigma units a static scene is flat to
 * ~1 dB across the whole axis and one threshold means the same everywhere.
 *
 * units "counts" (--raw exports): the older log encoding,
 * `m = 10^(code/255 * log10(1+peak)) - 1`, kept so the "what unprocessed data
 * looks like" demo still decodes.
 */

/** Display / audio full scale, in noise sigmas. A static scene tops out near
 * 6 sigma on real captures; a solid echo goes well past it and simply clips,
 * which is what a full-scale reading should mean. */
export const FULL_SIGMA = 8;

export class Session {
  constructor(meta, codes) {
    this.meta = meta;
    this.codes = codes; // Uint8Array, frame-major (nFrames, nChannels, nSamples)
    // opt-in: a pre-sigma export has no `units` and must NOT be read as
    // sigmas — its code 28 would decode as 3.5 and clear the gate
    this.sigmaUnits = meta.units === "sigma";
    this.sigmaPerCode = meta.sigmaPerCode || 0.125;
    this.logPeak = Math.log10(1 + (meta.peak || 1));
    this._frame = new Float32Array(meta.nChannels * meta.nSamples);
  }

  /**
   * One code -> noise sigmas. A --raw (counts) file has no noise estimate at
   * all, so it is mapped onto the same 0..FULL_SIGMA RANGE by its own peak —
   * enough for the "this is what unprocessed data looks like" demo to render
   * and be gated, but the numbers are fractions of a file peak wearing
   * sigma's clothes, not significance.
   */
  decode(code) {
    if (this.sigmaUnits) return code * this.sigmaPerCode;
    const m = code === 0 ? 0 : Math.pow(10, (code / 255) * this.logPeak) - 1;
    return (m / Math.max(this.meta.peak, 1e-9)) * FULL_SIGMA;
  }

  static async load(stem) {
    const [meta, buf] = await Promise.all([
      fetch(`${stem}.json`).then((r) => {
        if (!r.ok) throw new Error(`${stem}.json: HTTP ${r.status}`);
        return r.json();
      }),
      fetch(`${stem}.bin`).then((r) => {
        if (!r.ok) throw new Error(`${stem}.bin: HTTP ${r.status}`);
        return r.arrayBuffer();
      }),
    ]);
    const codes = new Uint8Array(buf);
    const want = meta.nFrames * meta.nChannels * meta.nSamples;
    if (codes.length !== want) {
      throw new Error(`${stem}.bin is ${codes.length} bytes, metadata says ${want}`);
    }
    return new Session(meta, codes);
  }

  get nFrames() { return this.meta.nFrames; }
  get nSamples() { return this.meta.nSamples; }
  get nChannels() { return this.meta.nChannels; }
  get frameHz() { return this.meta.frameHz; }

  /** Range axis (cm) of one channel. */
  rangeCm(ch) { return this.meta.rangeCm[ch]; }

  /** Channel indices whose tx === rx — the two "ears". */
  get pulseEcho() { return this.meta.pulseEcho; }

  /**
   * One channel of one frame, decoded to magnitude, into a reused buffer.
   * Reused because this runs per frame per channel inside the render loop;
   * allocating here would hand the GC ~50 arrays a second.
   */
  profile(frame, ch, out) {
    const { nChannels, nSamples } = this.meta;
    const base = (frame * nChannels + ch) * nSamples;
    const dst = out && out.length === nSamples ? out : new Float32Array(nSamples);
    for (let i = 0; i < nSamples; i++) dst[i] = this.decode(this.codes[base + i]);
    return dst;
  }

  /** Hardware-rule targets for one frame: [[cm, over], ...] per channel,
   * strongest first, or [] when the export predates them. */
  targetsAt(frame, ch) {
    return this.meta.targets?.[frame]?.[ch] ?? [];
  }

  /** Peak magnitude and its range bin, for the readouts. */
  peakOf(frame, ch) {
    const { nChannels, nSamples } = this.meta;
    const base = (frame * nChannels + ch) * nSamples;
    let best = 0, at = 0;
    for (let i = 0; i < nSamples; i++) {
      if (this.codes[base + i] > best) { best = this.codes[base + i]; at = i; }
    }
    return { mag: this.decode(best), bin: at, cm: this.meta.rangeCm[ch][at] };
  }
}
