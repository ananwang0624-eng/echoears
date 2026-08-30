"""✅ 跑单元测试

点右上角 ▶ Run 按钮直接运行。不需要硬件,不需要数据文件。
改过 echoears/ 下的代码之后跑一下,确认没弄坏东西。
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import REPO, banner, ensure_py39  # noqa: E402

ensure_py39()
banner("单元测试")
raise SystemExit(subprocess.call(
    [sys.executable, "-m", "pytest", "tests/", "-v"], cwd=str(REPO)))
