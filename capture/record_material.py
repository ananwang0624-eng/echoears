"""🧶 材质对比 — 30 s(听力测验题库)

点右上角 ▶ Run。板子插好,先跑过 run/2_apply_queue.py。

物理:选定 60 cm 一个固定位置(桌上做个记号)。
录时:硬面(书/硬纸板)放记号处 10 秒 → 拿走空 5 秒 →
      软物(毛衣团/抱枕)放同一位置 10 秒 → 拿走。
用途:同距离、不同材质 —— 硬面回波响亮,软物哑几个量级。
      测验问法:"两段回波在同一距离,哪段是毛衣?"

多录几遍就多点几次 ▶,每次生成新的带时间戳文件,不覆盖。
输出 -> out/capture/material_<时间>.npz + manifest.json 追加一行。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="material", seconds=30,
    note="材质:60 cm 记号处 硬书 10 s → 空 5 s → 毛衣团 10 s",
))
