#!/usr/bin/env python3
"""Check the numbers the docs claim against the code and the shipped data.

    python tools/check_docs.py            # report
    python tools/check_docs.py --strict   # exit 1 on any mismatch (CI)

Exists because documented numbers drifted three separate times in one
working session — a TVG figure computed at the wrong exponent, a range-spread
row computed on a different quantity than the file it described, and a
false-alarm rate that conflated two files with two range bands. Each was
caught late, on re-measurement, never at edit time. A number a script can re-derive should not
be a thing a human has to remember to update.

Only checks claims that are mechanically derivable. Prose, judgement calls
and hardware observations are out of scope by design — see HANDOFF.md, which
states in its own table which of those can and cannot be trusted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from echoears import profile as prof  # noqa: E402

BANDS = [(20, 40), (40, 80), (80, 140), (140, 250)]


def _sigma_and_axis(stem: str):
    meta = json.loads((REPO / "web" / "data" / f"{stem}.json").read_text())
    codes = np.fromfile(REPO / "web" / "data" / f"{stem}.bin", dtype=np.uint8)
    codes = codes.reshape(meta["nFrames"], meta["nChannels"], meta["nSamples"])
    return meta, codes * meta["sigmaPerCode"]


def checks() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        out.append((name, ok, detail))

    # --- the gate default must agree in three places ----------------------
    audio = (REPO / "web" / "js" / "audio.js").read_text()
    html = (REPO / "web" / "index.html").read_text()
    live = (REPO / "apps" / "live.py").read_text()
    js_gate = float(re.search(r"gate:\s*([\d.]+)", audio).group(1))
    html_gate = float(re.search(r'id="gate"[^>]*value="([\d.]+)"', html).group(1))
    py_gate = float(re.search(r'"--gate", type=float, default=([\d.]+)', live).group(1))
    check("gate default agrees: audio.js / index.html / apps/live.py",
          js_gate == html_gate == py_gate,
          f"{js_gate} / {html_gate} / {py_gate}")

    js_full = float(re.search(r"FULL_SIGMA\s*=\s*([\d.]+)", audio).group(1))
    data_full = float(re.search(r"FULL_SIGMA\s*=\s*([\d.]+)",
                                (REPO / "web" / "js" / "data.js").read_text()).group(1))
    py_full = float(re.search(r'"--full-scale", type=float, default=([\d.]+)',
                              live).group(1))
    check("full scale agrees: audio.js / data.js / apps/live.py",
          js_full == data_full == py_full, f"{js_full} / {data_full} / {py_full}")

    # --- the README's flatness table --------------------------------------
    meta, sig = _sigma_and_axis("scene233")
    ax = np.array(meta["rangeCm"][meta["ears"][1]])
    ears = meta["ears"]
    v = [np.percentile(sig[:, ears, :][:, :, (ax >= lo) & (ax < hi)], 95)
         for lo, hi in BANDS]
    spread = 20 * np.log10(max(v) / min(v))
    readme = (REPO / "README.md").read_text()
    row = re.search(r"\|\s*\*\*noise sigmas\*\*\s*\|([^|]+)\|([^|]+)\|"
                    r"([^|]+)\|([^|]+)\|\s*\*\*([\d.]+) dB\*\*", readme)
    claimed = [float(row.group(i)) for i in range(1, 5)]
    claimed_spread = float(row.group(5))
    check("README sigma row matches web/data/scene233",
          all(abs(a - b) < 0.02 for a, b in zip(v, claimed))
          and abs(spread - claimed_spread) < 0.05,
          f"measured {[round(x,2) for x in v]} {spread:.2f} dB "
          f"vs claimed {claimed} {claimed_spread} dB")

    # --- the false-alarm figures, read OUT OF the README then verified ----
    # (hardcoding the expected value here would reproduce the exact disease
    #  this script exists to treat: a number remembered instead of derived)
    fa = re.search(r"([\d.]+)%\s*\(`scene233`\)[^%]*?([\d.]+)%\s*\(`empty233`\)",
                   readme)
    if not fa:
        check("README states false-alarm rates for both files", False,
              "could not find the sentence")
    else:
        for stem, want in [("scene233", float(fa.group(1))),
                           ("empty233", float(fa.group(2)))]:
            m, s = _sigma_and_axis(stem)
            rate = 100 * (s[:, m["ears"], :] > js_gate).mean()
            check(f"{stem} false-alarm rate matches the README's {want}%",
                  abs(rate - want) < 0.005, f"measured {rate:.3f}%")

    # --- shipped datasets are what the page says they are -----------------
    for stem, units in [("scene233", "sigma"), ("empty233", "sigma"),
                        ("scene233raw", "counts")]:
        m = json.loads((REPO / "web" / "data" / f"{stem}.json").read_text())
        listed = f'value="data/{stem}"' in html
        check(f"{stem}: units {units}, offered in the dropdown",
              m.get("units") == units and listed,
              f"units={m.get('units')} listed={listed}")

    # --- detect.py's threshold copy must match the installed queue --------
    from echoears import detect
    qpath = Path.home() / "Documents/GitHub/ultrasonic/firmware/txrot/txrot_long233_tx160.json"
    if qpath.is_file():
        th = json.loads(qpath.read_text())["meas_cfg"][0]["thresholds"]
        check("detect.py threshold curve matches the installed queue",
              th["stop_index"] == detect.STOP_INDEX
              and th["threshold"] == detect.THRESHOLD,
              f"queue {th['threshold']} vs detect.py {detect.THRESHOLD}")
    else:
        check("detect.py threshold curve matches the installed queue", True,
              "queue file absent on this machine (CI) — copy not checkable")

    # --- test count claimed in the docs -----------------------------------
    # the collected count, not `def test_`: parametrised cases are runs too,
    # and the docs quote what pytest prints
    import subprocess
    coll = subprocess.run([sys.executable, "-m", "pytest", "tests/",
                           "--collect-only", "-q"],
                          cwd=REPO, capture_output=True, text=True)
    m = re.search(r"(\d+) tests? collected", coll.stdout)
    n_tests = int(m.group(1)) if m else -1
    for doc in ["HANDOFF.md", "run/README.md", "README.md", "docs/DEFENCE.md"]:
        txt = (REPO / doc).read_text()
        # only lines that are about THIS suite — HANDOFF also mentions the
        # predecessor project's test count, which is not ours to keep current
        nums = set()
        for line in txt.splitlines():
            if "TerraTone" in line or "predecessor" in line:
                continue
            nums.update(int(x) for x in re.findall(r"(\d+)\s*tests", line))
        stale = {n for n in nums if 10 < n < 500 and n != n_tests}
        check(f"{doc} test count ({n_tests} collected)",
              not stale, f"stale numbers mentioned: {sorted(stale)}" if stale else "ok")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    bad = 0
    for name, ok, detail in checks():
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}\n        {detail}")
        bad += not ok
    print(f"\n{bad} mismatch(es)")
    return 1 if bad and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
