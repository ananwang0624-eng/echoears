"""📐 Show the active queue and its range

Click ▶ Run (top right). Read-only, changes nothing.

If it shows something unexpected, the upstream setup_mac_py39.py probably
overwrote the plugin registry — just click run/2_apply_queue.py again.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import QUEUE, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("Current meas queue status")

rc = run_app("tools/use_queue.py", ["status"])
if rc == 0:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.use_queue import TOML, _current
    live = _current(TOML.read_text()).get('per_sensor_defaults."icu-10201"')
    if live:
        print()
        rc = run_app("tools/measqueue.py", ["show", live])
        if Path(live).name != QUEUE.name:
            print(f"\n  ⚠️  this is not the echoears queue ({QUEUE.name}).")
            print("     Click run/2_apply_queue.py to restore it.")
raise SystemExit(rc)
