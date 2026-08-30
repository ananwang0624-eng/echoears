"""📚 双物体 — 30 s(一次 ping,两个回波)

点右上角 ▶ Run。板子插好,先跑过 run/2_apply_queue.py。

物理:两件硬面物体(书、硬纸板)立在 40 cm 和 90 cm,都正对传感器。
录时:前 10 秒全部静止;然后把【近的那件】慢慢滑到 60 cm 再滑回,
      远的始终不动;最后 5 秒再全静止。
用途:一次 ping 两个回波 = 两个声部。Targets 模式听到持续和弦;
      Sonar 模式只有被移动的那件在唱 —— 同一场景讲透两种听法。

多录几遍就多点几次 ▶,每次生成新的带时间戳文件,不覆盖。
输出 -> out/capture/chord_<时间>.npz + manifest.json 追加一行。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="chord", seconds=30,
    note="双物体:40+90 cm 静置 10 s → 近者滑 40↔60 cm,远者不动 → 静 5 s",
))
