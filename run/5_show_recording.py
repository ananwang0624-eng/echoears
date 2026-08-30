"""🔍 看一段录音的距离剖面(ASCII 图)

点右上角 ▶ Run 按钮直接运行。不出声,只看数据。

会打印 9 个通道各自的能量沿距离的分布,以及去掉静态杂波后的分布。
去杂波前峰值在 1-3 cm 的是振铃;去杂波后峰值移到 5-10 cm 的才是真目标。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import (ARCHIVE_ODR, SAMPLE_NPZ, ask, banner,  # noqa: E402
                       ensure_py39, run_app)

ensure_py39()
banner("录音距离剖面")

npz = Path(ask("npz 路径", str(SAMPLE_NPZ))).expanduser()
if not npz.is_file():
    raise SystemExit(f"\n  找不到文件:{npz}")
odr = ask("这段录音的 CIC ODR", ARCHIVE_ODR, int)

raise SystemExit(run_app("apps/show.py", [npz, "--odr", odr, "--static"]))
