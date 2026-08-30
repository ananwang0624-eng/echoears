"""📐 规划一个量程 — 只算,不改任何文件

点右上角 ▶ Run 按钮直接运行。

输入你想要的量程,它会告诉你每个 ODR 下:
  - 需要多少样本(340 是缓冲上限)
  - SPI 读出要多久(决定帧率会不会掉)
  - 推荐哪个 ODR

想真的写出来,改用 run/2_apply_queue.py(固定 120 cm),
或者照它最后打印的命令自己跑 tools/measqueue.py write。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import N_TX, ask, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("量程规划", "只计算,不写文件")

range_cm = ask("目标量程(cm,pulse-echo 物距)", 120, float)
odr_ms = ask("当前拍间隔 odr_ms", 26, int)
n_tx = ask("传感器数(镜腿两颗=2)", N_TX, int)

raise SystemExit(run_app("tools/measqueue.py", [
    "plan", "--range-cm", range_cm, "--odr-ms", odr_ms, "--n-tx", n_tx]))
