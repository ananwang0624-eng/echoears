"""Shared engine for capture/record_*.py — one shot per ▷ click.

Mirrors the ultrasonic repo's capture/engine pattern: every launcher is a
few lines naming its shot; this module does the rest (py39 re-exec, queue
guard, bring-up, countdown, record via tools/record.capture, manifest
append, next-step commands). Re-running a launcher never overwrites —
each run gets a timestamped file, so "录多几遍" is just clicking ▷ again.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "run"))

from _launcher import QUEUE, banner, ensure_py39  # noqa: E402

OUT_DIR = REPO / "out" / "capture"


def _queue_guard() -> None:
    # Wrong queue = silently wrong range axis. Same hard stop as run/1.
    from tools.use_queue import TOML, _current

    live = _current(TOML.read_text()).get('per_sensor_defaults."icu-10201"')
    if not live or Path(live).name != QUEUE.name:
        print(f"\n  ⚠️  当前生效队列是 {Path(live).name if live else '未设置'},"
              f"不是 {QUEUE.name}")
        print("     请先运行 run/2_apply_queue.py,再回来跑这个。\n")
        raise SystemExit(1)
    print(f"  ✅ 队列已是 {QUEUE.name}(233 cm)\n")


def record_shot(label: str, seconds: float, note: str) -> int:
    ensure_py39()
    banner(f"采集 · {label} ({seconds:.0f} s)", "Ctrl-C 取消(不写文件)")
    _queue_guard()

    # resolve BEFORE the EVK stack loads: its bootstrap chdir()s
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{label}_{time.strftime('%Y%m%d_%H%M%S')}.npz"

    from echoears.sources import LiveSource
    from tools.record import capture

    print(f"  动作:{note}\n")
    print("[capture] 起板中 (烧录+标定约 20 s) ...")
    with LiveSource() as src:
        while not src.channels:
            if not src.poll():
                time.sleep(0.02)
        print(f"[capture] 就绪:{len(src.channels)} 通道 @ {src.frame_hz:.1f} Hz")
        input("  摆好位置后按 Enter 开录: ")
        for n in (3, 2, 1):
            print(f"  {n} ...")
            time.sleep(1.0)
        print("  ● 录制中")
        entry = capture(src, seconds, label, note, out)

    mf = OUT_DIR / "manifest.json"
    entries = json.loads(mf.read_text()) if mf.exists() else []
    entries.append(entry)
    mf.write_text(json.dumps(entries, ensure_ascii=False, indent=2))

    py = sys.executable
    print(f"\n[capture] 已保存 -> {out}")
    print(f"[capture] 清单 {mf}({len(entries)} 条)\n")
    print("下一步(可选):")
    print(f"  # 试听回放\n  {py} {REPO}/apps/live.py --replay {out} --odr 4")
    print(f"  # 导出到网页离线 demo\n  {py} {REPO}/tools/export_web.py {out} "
          f"--odr 4 -o {REPO}/web/data/{out.stem} --title {label}")
    return 0
