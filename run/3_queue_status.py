"""📐 查看当前生效的队列 + 它的量程

点右上角 ▶ Run 按钮直接运行。不改任何东西,只读。

如果显示的不是 txrot_long120.json —— 多半是跑过上游的
tools/setup_mac_py39.py,它会用 EVK 克隆里的版本覆盖插件注册表。
重新点 run/2_apply_queue.py 即可。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import QUEUE, banner, ensure_py39, run_app  # noqa: E402

ensure_py39()
banner("当前 meas queue 状态")

rc = run_app("tools/use_queue.py", ["status"])
if rc == 0:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.use_queue import TOML, _current
    live = _current(TOML.read_text()).get('per_sensor_defaults."icu-10201"')
    if live:
        print()
        rc = run_app("tools/measqueue.py", ["show", live])
        if Path(live).name != QUEUE.name:
            print(f"\n  ⚠️  这不是 echoears 的队列({QUEUE.name})。")
            print("     点 run/2_apply_queue.py 装回去。")
raise SystemExit(rc)
