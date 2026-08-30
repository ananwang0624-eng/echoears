"""🕳 空场景基线 — 15 s

点右上角 ▶ Run。板子插好,先跑过 run/2_apply_queue.py。

物理:传感器前 1.5 m 内清空,你自己也别站在正前方。
录时:静置不动,确认视场内真的没东西。
用途:噪声基线 — 网页 demo 的"空"参照,σ 归一化的对照组。

多录几遍就多点几次 ▶,每次生成新的带时间戳文件,不覆盖。
输出 -> out/capture/empty_<时间>.npz + manifest.json 追加一行。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="empty", seconds=15,
    note="空场景基线:1.5 m 内无反射物,人离开正前方,静置",
))
