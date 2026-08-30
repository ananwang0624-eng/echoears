"""🖐 单手推拉 — 40 s(演示素材的主菜)

点右上角 ▶ Run。板子插好,先跑过 run/2_apply_queue.py。

物理:眼镜/支架摆稳,手掌对准【右】传感器(id 2)。
录时:从 1 m 慢慢推近到 20 cm 再拉回,重复 3-4 个来回;
      最后 10 秒改成快速挥动。
用途:离线 demo 的动态主素材 — 近=高音、动=声音跟着走。

多录几遍就多点几次 ▶,每次生成新的带时间戳文件,不覆盖。
输出 -> out/capture/hand_<时间>.npz + manifest.json 追加一行。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _engine

raise SystemExit(_engine.record_shot(
    label="hand", seconds=40,
    note="单手推拉:1 m ↔ 20 cm 慢速 3-4 回合,最后 10 s 快挥",
))
