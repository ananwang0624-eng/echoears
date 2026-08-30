"""📐 官方测距固件 · 换预设 — Short Range 等

点右上角 ▶ Run 按钮直接运行。

run/9 用 Long Range:为 2-5 m 的墙设计,近场门限 1600/800 counts,
手掌在 80 cm 内基本过不了线。这里可以换成:

  short    Short Range(默认):~1 cm/bin,60-135 cm 段门限只要 200,
           TX 阶梯降幅、ringdown 更短 —— 手掌友好,演示手部用这个
  static   Static Target Rejection:芯片端抑制静止目标,只报变化
  default  厂商出厂默认

其余和 run/9 完全一致:官方 gpt 固件、TX Opt、两个自发自收通道、
芯片自己报目标。txrot 同样会被覆盖,跑 run/8 自动烧回。
Ctrl-C 停止。开机约 20 秒(烧录)。
"""
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import REPO, ask, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("官方测距固件 · 换预设 (gpt · TX Opt · 2 通道)", "Ctrl-C 停止")


def _busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if _busy(8765) or _busy(8080):
    print("\n  已经有一份在跑了,直接打开页面。\n")
    webbrowser.open("http://localhost:8080")
    raise SystemExit(0)

import glob  # noqa: E402

if not glob.glob("/dev/cu.usbmodem*"):
    print("\n  ⚠️  没插板子。这条路必须有硬件(它要烧固件)。\n")
    raise SystemExit(1)

cfg = str(ask("预设 short / static / default", "short", str)).strip().lower()
if cfg not in ("short", "static", "default"):
    print(f"\n  ⚠️  不认识的预设 {cfg!r},用 short / static / default。\n")
    raise SystemExit(1)

print("  ⚠️  这会把官方测距固件烧进传感器,txrot 被覆盖 ——")
print("      想换回去:直接跑 run/8_web.py,它开板时会烧回 txrot。\n")

web = subprocess.Popen(
    [sys.executable, "-m", "http.server", "8080", "--directory",
     str(REPO / "web")],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(1.0)
    webbrowser.open("http://localhost:8080")
    print("  页面已打开 — 等下面打出「测距固件 … Hz」后:")
    print("    1. 强制刷新页面 (⌘⇧R)")
    print("    2. 点右上角「🔌 Live 连接实时硬件」")
    print("    3. 听感模式切到「Targets 目标」\n")
    raise SystemExit(run_app("tools/bridge.py", ["--rangefinder",
                                                 "--cfg", cfg]))
finally:
    web.terminate()
    try:
        web.wait(timeout=5)
    except Exception:      # noqa: BLE001
        web.kill()
