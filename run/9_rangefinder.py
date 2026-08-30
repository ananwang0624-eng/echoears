"""📏 官方测距固件 — 两通道 + Long Range + TX Opt

点右上角 ▶ Run 按钮直接运行。

和 run/8 的区别,只有一条,但很重要:

  run/8  txrot 固件 → 2×2 矩阵(自发自收 + 交叉收发),主机端做检测
  run/9  官方 gpt 固件 → 只有 2 个自发自收通道,芯片自己报目标

ICU-10201 只有一个算法槽。装上官方测距算法就得卸掉 txrot,交叉信道
(PC)也随之消失 —— 这是这条路唯一的代价。反过来也是自动的:再跑一次
run/8,它开板时会把 txrot 烧回去。

换来的是:芯片按绝对门限报「那里有什么」,东西不动也一直报;
Long Range 序列 + TX Opt 打开,近场门限比我们自己那条细得多。

浏览器里把「听感模式」切到 Targets 目标,听到的就是芯片的判断。
Ctrl-C 停止。开机约 20 秒(烧录)。
"""
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import REPO, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("官方测距固件 (gpt · Long Range · TX Opt · 2 通道)", "Ctrl-C 停止")


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

print("  ⚠️  这会把官方测距固件烧进传感器,txrot 被覆盖 ——")
print("      交叉收发(PC)通道在本模式下不存在。")
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
    # no --odr-ms: the Long Range sequence sets its own floor (70 ms)
    raise SystemExit(run_app("tools/bridge.py", ["--rangefinder"]))
finally:
    web.terminate()
    try:
        web.wait(timeout=5)
    except Exception:      # noqa: BLE001
        web.kill()
