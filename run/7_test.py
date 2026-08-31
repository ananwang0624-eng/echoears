"""✅ Run the unit tests

Click ▶ Run (top right). Needs no hardware and no data files.
Run it after touching anything under echoears/ to confirm nothing broke.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _launcher import REPO, banner, ensure_py39  # noqa: E402

ensure_py39()
banner("Unit tests")
raise SystemExit(subprocess.call(
    [sys.executable, "-m", "pytest", "tests/", "-v"], cwd=str(REPO)))
