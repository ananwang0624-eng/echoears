"""🚶 走近走远 — 20 s

点右上角 ▶ Run。板子插好,先跑过 run/2_apply_queue.py。

物理:传感器朝向开阔方向,留出 2 m 走道。
录时:从 2 m 外正面走近到 0.5 m,停一秒,再退回去。重复两次。
用途:全身大目标的听感 — 和手部小目标对照。

多录几遍就多点几次 ▶,每次生成新的带时间戳文件,不覆盖。
输出 -> out/capture/walk_<时间>.npz + manifest.json 追加一行。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="walk", seconds=20,
    note="走近走远:2 m → 0.5 m 停一秒 → 退回,重复两次",
))
