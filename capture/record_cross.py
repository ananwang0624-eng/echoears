"""↔️ 左右横穿 — 20 s(双耳声像的招牌)

点右上角 ▶ Run。板子插好,先跑过 run/2_apply_queue.py。

物理:传感器前方 ~1 m 留出左右各一步的空间。
录时:从最左侧走到最右侧(约 4 秒),停 2 秒,再走回来。共两趟。
用途:回波从左耳滑到右耳 —— 戴耳机听得到"有人从左边走过去"。
      瀑布图上左通道条纹先亮、右通道后亮。

多录几遍就多点几次 ▶,每次生成新的带时间戳文件,不覆盖。
输出 -> out/capture/cross_<时间>.npz + manifest.json 追加一行。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="cross", seconds=20,
    note="横穿:~1 m 处 最左→最右(4 s)停 2 s→走回,共两趟",
))
