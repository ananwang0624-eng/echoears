"""🙌 双手二重奏 — 30 s

点右上角 ▶ Run。板子插好,先跑过 run/2_apply_queue.py。

物理:左手对左传感器(id 3),右手对右传感器(id 2)。
录时:两手各自独立推拉,节奏错开(左慢右快),
      让两只耳朵听到不同的声部。
用途:双耳分离的听觉证据 — 左耳左手、右耳右手。

多录几遍就多点几次 ▶,每次生成新的带时间戳文件,不覆盖。
输出 -> out/capture/duet_<时间>.npz + manifest.json 追加一行。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="duet", seconds=30,
    note="双手二重奏:左手对左传感器慢、右手对右传感器快,独立推拉",
))
