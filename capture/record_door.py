"""🚪 场景事件:开关门 — 20 s(可选)

点右上角 ▶ Run。板子插好,先跑过 run/2_apply_queue.py。

物理:传感器量程(2.3 m)内有一扇门或柜门。
录时:开、关一次,动作自然,别的都不动。
用途:场景听力测验素材 — "只听声音猜发生了什么"。

多录几遍就多点几次 ▶,每次生成新的带时间戳文件,不覆盖。
输出 -> out/capture/door_<时间>.npz + manifest.json 追加一行。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="door", seconds=20,
    note="场景事件:量程内开、关一次门/柜,其余不动",
))
