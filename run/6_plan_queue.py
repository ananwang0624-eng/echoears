"""📐 Plan a range — calculates only, writes nothing

Click ▶ Run (top right).

Give it the range you want; for each ODR it reports:
  - samples needed (340 is the buffer cap)
  - SPI readout time (decides whether the frame rate drops)
  - which ODR it recommends

To actually write a queue, use run/2_apply_queue.py, or run the
tools/measqueue.py write command it prints at the end.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import N_TX, ask, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("Range planning", "calculation only, no files written")

range_cm = ask("Target range (cm, pulse-echo)", 120, float)
odr_ms = ask("Beat interval odr_ms", 26, int)
n_tx = ask("Sensor count (temple pair = 2)", N_TX, int)

raise SystemExit(run_app("tools/measqueue.py", [
    "plan", "--range-cm", range_cm, "--odr-ms", odr_ms, "--n-tx", n_tx]))
