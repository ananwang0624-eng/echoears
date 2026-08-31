/**
 * WebSocket client for the live rig.
 *
 * Protocol (see tools/bridge.py):
 *   first message   {"type":"meta", nChannels, nSamples, frameHz, peak,
 *                    channels, pulseEcho, rangeCm}
 *   then, per frame {"type":"frame", mag:[[...], ...]}  one array per
 *                   channel — all of the 2x2, not just the ear pair. Values
 *                   are uint8 codes on the exporter's grid; multiply by
 *                   meta.sigmaPerCode for noise sigmas.
 *
 * JSON rather than binary on purpose: four ~300-value integer arrays at
 * ~19 Hz is ~120 KB/s over loopback — cheap, and being able to read the stream in
 * devtools is worth more than the bytes here.
 */

export class LiveBridge {
  /**
   * Retries every 2 s for ~40 s before giving up: run/8_web.py opens the
   * browser ~1 s in, but the bridge needs ~20 s to flash and calibrate the
   * board — a one-shot connect punished everyone who clicked early.
   */
  constructor(url, { onMeta, onFrame, onError, onWait }) {
    this.meta = null;
    this.bufs = null;
    this.closed = false;
    this.tries = 0;
    this.handlers = { onMeta, onFrame, onError, onWait };
    this.url = url;
    this._connect();
  }

  _connect() {
    const { onMeta, onFrame, onError, onWait } = this.handlers;
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      onError(e.message);
      return;
    }
    const retry = () => {
      if (this.closed || this.meta) { if (this.meta) onError("connection lost"); return; }
      if (++this.tries > 20) { onError("no bridge after 40 s"); return; }
      onWait?.(`waiting for the bridge … ${this.tries * 2} s (flash+calibration ~20 s)`);
      setTimeout(() => this._connect(), 2000);
    };
    this.ws.onerror = () => {};
    this.ws.onclose = (e) => { if (!e.wasClean || !this.meta) retry(); };
    this.ws.onmessage = (ev) => {
      if (this.closed) return;    // a queued frame must not clobber replay
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "meta") {
        // the wire format changed units (counts -> sigmas) once already;
        // a mismatch must be loud, not a silently 8x-hot noise floor
        if ((msg.protocol ?? 1) !== 2) {
          onError(`bridge protocol ${msg.protocol ?? 1}, page needs 2 — update one side`);
          this.close();
          return;
        }
        this.meta = msg;
        this.bufs = Array.from({ length: msg.nChannels },
                               () => new Float32Array(msg.nSamples));
        onMeta(msg);
      } else if (msg.type === "frame" && this.meta) {
        const spc = this.meta.sigmaPerCode ?? 0.125;   // same default as data.js
        for (let c = 0; c < this.bufs.length; c++) {
          const src = msg.mag[c];
          if (!src) continue;
          for (let i = 0; i < src.length; i++) this.bufs[c][i] = src[i] * spc;
        }
        onFrame(this.bufs, msg.tg);
      }
    };
  }

  close() {
    this.closed = true;
    try { this.ws?.close(); } catch { /* already gone */ }
  }
}
