"""▶ 回放录音 — 不需要硬件

点右上角 ▶ Run 按钮直接运行。

用一段已录好的 npz 跑**完全相同**的音频管线(GrainSynth + 基线去杂波 +
立体声输出)。板子没插、在别的地方调音、或者想反复听同一段时用这个。

按 Enter 用默认那段 hand_moving(手在传感器前移动,30 秒)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import (ARCHIVE_ODR, OUT, SAMPLE_NPZ, ask, banner,  # noqa: E402
                       ensure_py39, run_app)

ensure_py39()
banner("回放(无硬件)", "同一条音频管线,数据来自录音")

npz = Path(ask("npz 路径", str(SAMPLE_NPZ))).expanduser()
if not npz.is_file():
    raise SystemExit(f"\n  找不到文件:{npz}")

odr = ask("这段录音的 CIC ODR", ARCHIVE_ODR, int)
seconds = ask("播放时长(秒,0=整段)", 30, int)
gain = ask("音量 0.1-1.0", 0.6, float)

args = ["--replay", npz, "--odr", odr, "--gain", gain,
        "--wav", OUT / "replay.wav"]
if seconds:
    args += ["--seconds", seconds]
raise SystemExit(run_app("apps/live.py", args))
