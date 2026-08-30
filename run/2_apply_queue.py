"""📐 装上 233 cm meas queue

点右上角 ▶ Run 按钮直接运行。第一次用、或跑过上游 setup_mac_py39.py 之后跑这个。

原理:量程 = RX 指令的监听时长(SMCLK)。
      ODR 只决定这段窗口被切成多少样本(受 340 缓冲上限约束)。

  233 cm 队列: odr=5, 310 样本, 窗口 19,840 SMCLK (7.03 ms), 38.5 Hz
               两颗传感器的轮转只占 3 颗时的一半读出预算,ODR=5 才放得下

它改的是 EVK 插件注册表里 [plugins.txrot] 指向的文件,不动传感器固件。
原始 toml 已备份为 PysonicPlugins.toml.echoears-bak,
要完全撤销 echoears 的改动:tools/use_queue.py restore
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import QUEUE, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("装上 meas queue (233 cm)", QUEUE.name)

if not QUEUE.is_file():
    print(f"\n  队列文件不存在,先生成:{QUEUE}\n")
    rc = run_app("tools/measqueue.py", [
        "write", "--range-cm", 234, "--odr", 4, "--tx", 160,
        "-o", QUEUE, "--force"])
    if rc:
        raise SystemExit(rc)

rc = run_app("tools/use_queue.py", ["set", QUEUE])
if rc == 0:
    print("\n  ✅ 装好了。下一步:run/1_listen.py")
raise SystemExit(rc)
