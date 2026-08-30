"""🌐 网页版实时收听 — 一键启动

点右上角 ▶ Run 按钮直接运行,零输入。

它做三件事:
  1. 起网页服务器  http://localhost:8080  (静态,web/ 目录)
  2. 起硬件桥接器  ws://localhost:8765    (板子 → WebSocket)
  3. 自动打开浏览器

浏览器里点右上角「🔌 连接实时硬件」,戴上耳机就能听。
2×2 通道网格 + 每通道混音条(开关/音量/声像/八度)都在页面上,
PC 交叉信道默认关闭,勾上开关就能听到。

Ctrl-C 停止全部。开机约 20 秒(烧录 + 相位标定)。
"""
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import (LIVE_ODR, QUEUE, REPO, banner, ensure_py39,  # noqa: E402
                       run_app)

ensure_py39()
banner("网页版实时收听 (233 cm, 2×2 通道)", "Ctrl-C 停止")


def _busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


# Double-clicked twice? The first instance is still serving — just reopen the
# page instead of fighting it for the ports.
if _busy(8765) or _busy(8080):
    print("\n  已经有一份在跑了,直接打开页面。\n")
    webbrowser.open("http://localhost:8080")
    raise SystemExit(0)

# No board plugged in? Fall back to replaying the shipped recording — the
# whole web app works identically, just from disk instead of the rig.
import glob

REPLAY = REPO / "out" / "scene233.npz"
bridge_args = []
serve_only = False
if not glob.glob("/dev/cu.usbmodem*"):
    if REPLAY.is_file():
        print(f"\n  🔌 没插板子 — 桥接器用录音回放:{REPLAY.name}\n")
        bridge_args = ["--replay", str(REPLAY), "--odr", str(LIVE_ODR)]
    else:
        # web/data ships a browser-side replay that needs NO bridge at all —
        # a fresh clone (out/ is gitignored) must still get the page.
        print("\n  🔌 没插板子、没有 npz — 只开网页,用页面内置的录音回放。\n")
        serve_only = True
else:
    # Same guard as 1_listen: a wrong queue gives a silently wrong range axis.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.use_queue import TOML, _current  # noqa: E402

    live = _current(TOML.read_text()).get('per_sensor_defaults."icu-10201"')
    if not live or Path(live).name != QUEUE.name:
        print(f"\n  ⚠️  当前生效队列是 {Path(live).name if live else '未设置'},"
              f"不是 {QUEUE.name}")
        print("     请先运行 run/2_apply_queue.py,再回来跑这个。\n")
        raise SystemExit(1)
    print(f"  ✅ 队列已是 {QUEUE.name}(233 cm)\n")

web = subprocess.Popen(
    [sys.executable, "-m", "http.server", "8080", "--directory",
     str(REPO / "web")],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(1.0)
    webbrowser.open("http://localhost:8080")
    if serve_only:
        print("  页面已打开 — 直接按 ▶ Play 听录音。Ctrl-C 停止。\n")
        web.wait()
        raise SystemExit(0)
    print("  页面已打开 — 等桥接器打出「实时 … Hz」后,点「连接实时硬件」。\n")
    raise SystemExit(run_app("tools/bridge.py", bridge_args))
finally:
    web.terminate()
    try:
        web.wait(timeout=5)
    except Exception:                  # noqa: BLE001
        web.kill()
