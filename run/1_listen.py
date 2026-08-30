"""🎧 双耳收听 — 233 cm

点右上角 ▶ Run 按钮直接运行。
一路按 Enter 用默认值,或输入自己的数字。

需要:板子插好、耳机戴上。
开机约 20 秒(烧录 + 相位标定),然后开始出声。

左镜腿 → 左耳,右镜腿 → 右耳(两颗传感器,4 通道,20 Hz)。
两米多的范围 —— 可以从房间另一头走过来。

第一次跑?先点 run/2_apply_queue.py 把 meas queue 装上。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import (LIVE_ODR, ODR_MS, OUT, QUEUE, ask, banner,  # noqa: E402
                       ensure_py39, run_app)

ensure_py39()
banner("双耳收听 (233 cm, 双传感器 20 Hz)", "Ctrl-C 随时停止")

# 队列没装上的话,距离轴是错的 —— 而且不会报错,所以这里硬拦。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.use_queue import TOML, _current  # noqa: E402

live = _current(TOML.read_text()).get('per_sensor_defaults."icu-10201"')
if not live or Path(live).name != QUEUE.name:
    print(f"\n  ⚠️  当前生效队列是 {Path(live).name if live else '未设置'},"
          f"不是 {QUEUE.name}")
    print("     请先运行 run/2_apply_queue.py,再回来跑这个。\n")
    raise SystemExit(1)
print(f"  ✅ 队列已是 {QUEUE.name}(233 cm)\n")

seconds = ask("收听时长(秒)", 60, int)
gain = ask("音量 0.1-1.0", 0.6, float)
wav = OUT / "listen.wav"

raise SystemExit(run_app("apps/live.py", [
    "--odr", LIVE_ODR,
    "--odr-ms", ODR_MS,
    "--seconds", seconds,
    "--gain", gain,
    "--wav", wav,
]))
