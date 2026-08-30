"""🥁 空气演奏 — 40 s(把房间当乐器)

点右上角 ▶ Run。板子插好,先跑过 run/2_apply_queue.py。

物理:手掌对准右传感器,想象 30 / 50 / 80 cm 处悬着三块木琴键。
录时:有节奏地在三个距离之间跳:近-近-远-中、近-近-远-中……
      每拍停半秒让音高立住;最后 10 秒自由发挥,快慢混合。
用途:Tones 模式回放 = 一段三音旋律 —— 演示"这不只是传感器,
      是能演奏的乐器"。建议先空手练 2 分钟再录,录 2-3 遍挑最好的。

多录几遍就多点几次 ▶,每次生成新的带时间戳文件,不覆盖。
输出 -> out/capture/perform_<时间>.npz + manifest.json 追加一行。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="perform", seconds=40,
    note="演奏:30/50/80 cm 三个音位按节拍跳,每拍停半秒;末 10 s 自由",
))
