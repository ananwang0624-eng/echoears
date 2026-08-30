"""Shared plumbing for the click-to-run launchers in this folder.

Every script here is meant to be opened in VS Code and started with the ▶ Run
button — no arguments, no terminal invocation. Two things make that work:

1. `ensure_py39()` re-execs into the EVK interpreter if you started under the
   wrong one, so clicking Run always lands in a working environment.
2. `ask()` prints a default and accepts Enter, so the normal path is "click,
   press Enter a few times".
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ULTRASONIC = Path.home() / "Documents" / "GitHub" / "ultrasonic"
PY39 = ULTRASONIC / ".venv-py39" / "bin" / "python"
OUT = REPO / "out"

# Recording used by the no-hardware launchers when you just press Enter.
# Note: the archived recordings all predate this tool and were captured at
# ODR 6 (22 cm). Replay/inspect still read them — the axis is per-file, set by
# the --odr you pass. Only the live capture path is 233 cm now.
SAMPLE_NPZ = (ULTRASONIC / "matrix" / "data" / "m3x3_txrot_odr13"
              / "hand_moving" / "txrot_20260719_174149.npz")
ARCHIVE_ODR = 6

#: The one queue echoears captures with: 234 cm PE / 468 cm PC window,
#: ODR 4, 302 samples, 0.78 cm/bin, TX 160 cycles (the vendor Long Range
#: burst — the old 16-cycle burst left everything past ~65 cm in the noise;
#: A/B measured +9 dB at 0.5-1 m, real echoes to ~1.2 m, datasheet caps the
#: sensor at 1.7 m wall / 1.1 m post regardless of the window).
#:
#: The BEAT bounds everything: TX 0.9 ms + RX 13.7 ms + readout ~10.5 ms
#: = 25.1 ms, so odr_ms=26 (19.2 Hz). Mirrors sources.LiveSource.DEFAULT_ODR_MS
#: (kept literal here: this file must import before the py39 re-exec).
QUEUE = ULTRASONIC / "firmware" / "txrot" / "txrot_long233_tx160.json"
LIVE_ODR = 4
ODR_MS = 26
N_TX = 2          # two temple sensors, ids 2 and 3

_SENTINEL = "ECHOEARS_REEXEC"


def ensure_py39() -> None:
    """Re-exec under the EVK py3.9 venv if we are not already there."""
    if sys.version_info[:2] == (3, 9) or os.environ.get(_SENTINEL):
        return
    if not PY39.is_file():
        raise SystemExit(
            f"EVK interpreter not found: {PY39}\n"
            f"Run {ULTRASONIC}/tools/setup_mac_py39.py first."
        )
    print(f"[launcher] switching to {PY39}\n", flush=True)
    os.environ[_SENTINEL] = "1"
    # Unbuffered, or our prints land after the child process's output.
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.execv(str(PY39), [str(PY39), *sys.argv])


def banner(title: str, subtitle: str = "") -> None:
    print("=" * 62, flush=True)
    print(f"  {title}", flush=True)
    if subtitle:
        print(f"  {subtitle}", flush=True)
    print("=" * 62, flush=True)


def ask(label: str, default, cast=str):
    """Prompt showing the default; Enter accepts it."""
    raw = input(f"  {label} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        print(f"  ! 无法解析 {raw!r},用默认值 {default}")
        return default


def ask_yes(label: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    raw = input(f"  {label} [{d}]: ").strip().lower()
    return default if not raw else raw.startswith("y")


def arm_clean_shutdown() -> None:
    """Make a launcher die like Ctrl-C so its children get to close the board.

    Without this, SIGTERM to a launcher orphans the bridge (still holding the
    rig AND port 8765) and the web server (port 8080). The next run then sees
    the ports busy, prints "already running" and just reopens the browser —
    a silent stale-bridge state, worse than a wedge because nothing errors.
    """
    sys.path.insert(0, str(REPO))
    from echoears.sources import close_cleanly_on_sigterm
    close_cleanly_on_sigterm()


def run_app(script: str, args: list[str]) -> int:
    """Run one of the apps/ or tools/ entry points as a child process.

    A child process, not an import, because the EVK bootstrap chdir()s and
    monkeypatches on import — keeping that out of the launcher process means a
    failed run never leaves this one in a weird state.
    """
    OUT.mkdir(exist_ok=True)
    arm_clean_shutdown()
    cmd = [sys.executable, str(REPO / script), *[str(a) for a in args]]
    print("\n" + " ".join(cmd) + "\n", flush=True)
    sys.stdout.flush()  # child writes straight to the tty; don't interleave
    child = subprocess.Popen(cmd, cwd=str(REPO))
    try:
        return child.wait()
    except BaseException:
        # pass the stop down: the child is the one holding the rig, and
        # subprocess.call() would have left it orphaned and streaming
        child.terminate()
        try:
            child.wait(timeout=20)     # give its own cleanup time to run
        except subprocess.TimeoutExpired:
            child.kill()
        raise
