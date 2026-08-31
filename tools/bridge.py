#!/usr/bin/env python3
"""Stream live rig frames to the web app over WebSocket.

    python tools/bridge.py                 # hardware
    python tools/bridge.py --replay <npz> --odr 6    # no hardware, same wire format

Then open the web app and press "Live" (default ws://localhost:8765).

All four channels are sent as plain JSON magnitudes so the browser can show
the full 2x2 A-scan and mix any channel into either ear: 4 x 301 integers at
20 Hz is ~120 KB/s over loopback, and a stream you can read in devtools is
worth more than the bytes saved by packing it.

Deliberately dependency-free: a minimal RFC-6455 server in the stdlib is ~60
lines and beats asking the user to install `websockets` into the EVK's py3.9.
Text frames only, no fragmentation, no permessage-deflate — that is all the
browser needs for one-way JSON.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import socket
import struct
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echoears import detect, profile as prof  # noqa: E402
from echoears.sources import (LiveSource, ReplaySource,  # noqa: E402
                              close_cleanly_on_sigterm, pick_stereo_pe)

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def handshake(conn) -> bool:
    req = conn.recv(4096).decode("latin-1")
    key = next((l.split(":", 1)[1].strip() for l in req.split("\r\n")
                if l.lower().startswith("sec-websocket-key")), None)
    if not key:
        conn.close()
        return False
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    conn.send((
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).encode())
    return True


def send_text(conn, text: str) -> None:
    payload = text.encode()
    n = len(payload)
    header = bytearray([0x81])              # FIN + text opcode
    if n < 126:
        header.append(n)
    elif n < 1 << 16:
        header.append(126); header += struct.pack(">H", n)
    else:
        header.append(127); header += struct.pack(">Q", n)
    conn.sendall(bytes(header) + payload)


class Server:
    """Accepts one browser at a time; a second connection replaces the first."""

    def __init__(self, host="localhost", port=8765):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(1)
        self.client = None
        self.meta_json = None
        self.lock = threading.Lock()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        print(f"[bridge] ws://{host}:{port} — waiting for the browser")

    def _accept_loop(self):
        while True:
            conn, addr = self.sock.accept()
            try:
                if not handshake(conn):
                    continue
            except OSError:
                continue
            with self.lock:
                if self.client:
                    try: self.client.close()
                    except OSError: pass
                self.client = conn
                if self.meta_json:
                    try: send_text(conn, self.meta_json)
                    except OSError: self.client = None
            print(f"[bridge] browser connected {addr[0]}")

    def set_meta(self, meta: dict):
        self.meta_json = json.dumps(meta)
        with self.lock:
            if self.client:
                try: send_text(self.client, self.meta_json)
                except OSError: self.client = None

    def send(self, obj: dict):
        with self.lock:
            if not self.client:
                return
            try:
                send_text(self.client, json.dumps(obj))
            except OSError:
                # A dead browser must never take the capture down with it.
                self.client = None
                print("[bridge] browser disconnected")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rangefinder", action="store_true",
                    help="vendor gpt firmware + Long Range + TX opt, two "
                         "pulse-echo channels, on-chip target list. Evicts "
                         "txrot (no pitch-catch matrix); run/8 restores it.")
    ap.add_argument("--replay", type=Path, help="drive from an npz instead of hardware")
    ap.add_argument("--odr", type=int, default=4)
    ap.add_argument("--config", default=LiveSource.DEFAULT_CONFIG)
    ap.add_argument("--com-port", default=None)
    ap.add_argument("--port", type=int, default=8765)
    # Which temple is which: id 3 is the LEFT temple, id 2 the RIGHT —
    # confirmed by listening on the rig 2026-08-28 (the reverse sounded
    # mirrored). Channel order in the config says nothing about geometry.
    ap.add_argument("--left-sensor", type=int, default=3)
    ap.add_argument("--right-sensor", type=int, default=2)
    # None -> LiveSource.DEFAULT_ODR_MS, the single source of truth
    ap.add_argument("--odr-ms", type=int, default=None)
    ap.add_argument("--cfg", default="long",
                    help="rangefinder preset: long/short/static/default, "
                         "or an absolute json path")
    ap.add_argument("--alpha", type=float, default=0.02)
    args = ap.parse_args()
    # a bridge is usually stopped from outside (launcher, kill, IDE stop);
    # without this the board is left streaming and the next run needs a replug
    close_cleanly_on_sigterm()
    if args.replay:
        args.replay = args.replay.resolve()

    srv = Server(port=args.port)
    smclk = prof.smclk_for_odr(args.odr)
    # sigma=True: the browser gates in noise sigmas, and live must
    # speak the same units as the exported recordings
    base = prof.RunningBaseline(alpha=args.alpha, sigma=True)
    # Sigmas live in 0..~30, so rounding them to whole numbers would leave
    # eight usable levels. Quantise on the exporter's grid instead and let
    # the browser multiply back — same units, same resolution, both paths.
    SPC = 0.125

    def quantise(res):
        return np.clip(np.round(res / SPC), 0, 255).astype(np.uint8).tolist()

    def targets_of(mag, axes):
        """Hardware-rule targets from RAW counts, per channel — what the
        on-chip rangefinder would report. The baseline EMA doubles as the
        host-side ringdown cancellation the vendor curve assumes."""
        curve = detect.threshold_curve(mag.shape[1])
        est = base.baseline
        return [
            [[round(float(axes[c][i]), 1), round(o, 2)]
             for i, o in detect.detect_targets(
                 mag[c], curve,
                 static_est=None if est is None else est[c])]
            for c in range(mag.shape[0])
        ]

    def publish_meta(channels, n_samples, frame_hz, axes, ears):
        srv.set_meta({
            # bumped when the wire format changes meaning; the browser
            # refuses a mismatch rather than misscaling silently
            "protocol": 2,
            "type": "meta", "nChannels": len(channels), "nSamples": n_samples,
            "frameHz": frame_hz,
            # the browser decodes code*sigmaPerCode, exactly like a recording
            # peak means the CEILING code 255 stands for, in both paths
            "units": "sigma", "sigmaPerCode": SPC, "peak": 255 * SPC,
            "sigmaCeiling": 255 * SPC,
            "channels": [list(c) for c in channels],
            # every tx==rx channel, so the browser can lay out the 2x2 grid and
            # shade the diagonal; `ears` is which two of them get panned
            "pulseEcho": [i for i, (tx, rx) in enumerate(channels) if tx == rx],
            "ears": list(ears),
            "rangeCm": [[round(v, 4) for v in ax] for ax in axes],
        })

    if args.rangefinder:
        from echoears.rangefinder import RangeSource
        with RangeSource(args.com_port, odr_ms=args.odr_ms,
                         cfg=args.cfg) as src:
            # Each preset has its own CIC ODR (Long Range 2, Short Range 6)
            # and the bin width follows it — read it from the source, or the
            # axis is off by the ODR ratio.
            smclk = prof.smclk_for_odr(src.cic_odr)
            src.wait_for_data()
            ids = src.ids
            chans = [(s, s) for s in ids]          # pulse-echo only
            ears = (ids.index(args.left_sensor), ids.index(args.right_sensor))
            fop = [src.fop_hz.get(s, 176500.0) for s in ids]
            axes = [prof.range_axis_raw(s, s, fop[i], src.n_samples,
                                        smclk_per_sample=smclk,
                                        tx_smclk=prof.LIVE_TX_SMCLK)
                    for i, s in enumerate(ids)]
            # Frame rate is MEASURED, not derived: the presets schedule the
            # beats differently (Long Range delivers 14.3 Hz assembled at
            # odr_ms=35, Short Range 28.6 at the very same setting), and
            # every model we wrote down so far has been wrong for one of
            # them. Two seconds of counting is cheaper than a third theory.
            t0, cnt = time.time(), {s: 0 for s in ids}
            while time.time() - t0 < 2.0:
                for ev in src.poll():
                    cnt[ev["sid"]] = cnt.get(ev["sid"], 0) + 1
                time.sleep(0.005)
            hz = (min(cnt.values()) / 2.0) or src.frame_hz
            publish_meta(chans, src.n_samples, hz, axes, ears)
            print(f"[bridge] rangefinder {hz:.1f} Hz, "
                  f"ears=ch{ears[0]}/{ears[1]} — Ctrl-C to stop")
            n = 0
            pend: dict[int, dict] = {}
            while True:
                for ev in src.poll():
                    pend[ev["sid"]] = ev
                    if len(pend) < len(ids):
                        continue                    # wait for the whole beat
                    mag = np.stack([np.abs(pend[s]["iq"]) for s in ids])
                    res = base(mag)
                    tg = [[[round(cm, 1), round(a, 2)]
                           for cm, a in pend[s]["targets"]] for s in ids]
                    srv.send({"type": "frame", "mag": quantise(res), "tg": tg})
                    pend.clear()
                    n += 1
                    if n % 200 == 0:
                        live = sum(len(x) for x in tg)
                        print(f"  {n} frames  {live} targets this beat")
                time.sleep(0.005)



    if args.replay:
        src = ReplaySource(args.replay, smclk_per_sample=smclk)
        chans = src.channels
        ears = pick_stereo_pe(chans, args.left_sensor, args.right_sensor)
        tx_smclk = int(src.session.meta.get("tx_smclk", 0))
        axes = [prof.range_axis(src.session, c, smclk_per_sample=smclk,
                                tx_smclk=tx_smclk)
                for c in range(len(chans))]
        hz = src.frame_hz or 25.6
        publish_meta(chans, src.session.n_samples, hz, axes, ears)
        print(f"[bridge] replay {args.replay.name} @ {hz:.1f} Hz — Ctrl-C to stop")
        period = 1.0 / hz
        while True:                                   # loop the recording
            for _ts, mag in src.frames():
                res = base(mag)
                srv.send({"type": "frame", "mag": quantise(res),
                          "tg": targets_of(mag, axes)})
                time.sleep(period)
    else:
        with LiveSource(args.config, args.com_port, odr_ms=args.odr_ms) as src:
            while not src.channels:
                if not src.poll():
                    time.sleep(0.02)
            ears = pick_stereo_pe(src.channels, args.left_sensor, args.right_sensor)
            axes = [src.range_axis(c, smclk_per_sample=smclk)
                    for c in range(len(src.channels))]
            publish_meta(src.channels, src.n_samples, src.frame_hz, axes, ears)
            print(f"[bridge] live {src.frame_hz:.1f} Hz, ears=ch{ears[0]}/{ears[1]} "
                  f"— Ctrl-C to stop")
            n = 0
            while True:
                for _ts, mag in src.poll():
                    res = base(mag)
                    # All channels: the browser mixes and displays the full
                    # 2x2. Codes rather than floats halve the JSON and match
                    # the exporter's quantisation exactly.
                    srv.send({"type": "frame", "mag": quantise(res),
                              "tg": targets_of(mag, axes)})
                    n += 1
                    if n % 200 == 0:
                        print(f"  {n} frames  peak {res.max():.1f} sigma")
                time.sleep(0.005)
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
        rc = 0
    # The vendor serial stack starts non-daemon threads, so a normal exit
    # joins them and can block forever — which would look to the user like
    # "kill did nothing", provoking a second signal or a SIGKILL and
    # recreating the mid-stream wedge this whole path exists to avoid. The
    # board is already closed by here; nothing is left to flush but stdout.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
