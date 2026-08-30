#!/usr/bin/env python3
"""Point the txrot plugin at a meas queue, and show which one is live.

    python tools/use_queue.py status
    python tools/use_queue.py set ~/Documents/GitHub/ultrasonic/firmware/txrot/txrot_long120.json
    python tools/use_queue.py restore

Edits `[plugins.txrot]` in the venv's PysonicPlugins.toml, which is the copy
that actually wins at runtime (PLUGIN_CONFIG_DIRS is walked in reverse, so the
package dir is applied last). Sets BOTH `json_defaults` and
`per_sensor_defaults."icu-10201"` — the per-sensor entry overrides the global
one, so changing only one silently does nothing.

Re-running the upstream `tools/setup_mac_py39.py` overwrites this file from the
EVK clone; re-run `set` afterwards. `status` will tell you if that happened.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

ULTRASONIC = Path.home() / "Documents" / "GitHub" / "ultrasonic"
TOML = ULTRASONIC / ".venv-py39" / "evk_pkgs" / "invn" / "pysonic" / "PysonicPlugins.toml"

KEYS = ("json_defaults", 'per_sensor_defaults."icu-10201"')


def _txrot_block(text: str) -> tuple[int, int]:
    """(start, end) offsets covering [plugins.txrot] AND its sub-tables.

    The per-sensor mapping may be written either inline
    (`per_sensor_defaults."icu-10201" = ...`) or as a sub-table
    (`[plugins.txrot.per_sensor_defaults]`). Both forms must be found, or an
    edit produces a duplicate-key TomlDecodeError at load time.
    """
    m = re.search(r"^\[plugins\.txrot\]\s*$", text, re.M)
    if not m:
        raise SystemExit(f"[plugins.txrot] not found in {TOML}")
    end = len(text)
    for nxt in re.finditer(r"^\[([^\]]+)\]\s*$", text[m.end():], re.M):
        if not nxt.group(1).startswith("plugins.txrot"):
            end = m.end() + nxt.start()
            break
    return m.start(), end


def _current(text: str) -> dict[str, str | None]:
    lo, hi = _txrot_block(text)
    block = text[lo:hi]
    out = {}
    # inline form
    m = re.search(r'json_defaults\s*=\s*"([^"]*)"', block)
    out["json_defaults"] = m.group(1) if m else None
    # per-sensor: inline key, else the sub-table's icu-10201 entry
    m = re.search(r'per_sensor_defaults\."icu-10201"\s*=\s*"([^"]*)"', block)
    if not m:
        sub = re.search(r"^\[plugins\.txrot\.per_sensor_defaults\]\s*$", block, re.M)
        if sub:
            m = re.search(r'^\s*"?icu-10201"?\s*=\s*"([^"]*)"',
                          block[sub.end():], re.M)
    out['per_sensor_defaults."icu-10201"'] = m.group(1) if m else None
    return out


def cmd_status(_args) -> int:
    text = TOML.read_text()
    cur = _current(text)
    print(f"toml: {TOML}\n")
    paths = set()
    for k, v in cur.items():
        mark = "ok" if v and Path(v).is_file() else "MISSING" if v else "unset"
        print(f"  {k:34s} = {v}   [{mark}]")
        if v:
            paths.add(v)
    if len(paths) > 1:
        print("\n  ⚠ the two keys disagree — per_sensor_defaults wins at runtime.")
    elif paths:
        p = Path(paths.pop())
        print(f"\n  live queue: {p.name}")
        print(f"  decode it:  python tools/measqueue.py show {p}")
    return 0


def _set_keys(text: str, value: str) -> str:
    """Rewrite both queue paths, respecting whichever TOML form is in use."""
    lo, hi = _txrot_block(text)
    block = text[lo:hi]

    # 1. json_defaults (always inline)
    pat = re.compile(r'json_defaults\s*=\s*"[^"]*"')
    if pat.search(block):
        block = pat.sub(f'json_defaults = "{value}"', block)
    else:
        block = block.rstrip("\n") + f'\njson_defaults = "{value}"\n'

    # 2. per-sensor: edit whichever form exists; never introduce a second one.
    inline = re.compile(r'per_sensor_defaults\."icu-10201"\s*=\s*"[^"]*"')
    sub = re.search(r"^\[plugins\.txrot\.per_sensor_defaults\]\s*$", block, re.M)
    if inline.search(block):
        block = inline.sub(f'per_sensor_defaults."icu-10201" = "{value}"', block)
    elif sub:
        head, tail = block[: sub.end()], block[sub.end():]
        entry = re.compile(r'^(\s*"?icu-10201"?\s*=\s*)"[^"]*"', re.M)
        tail = (entry.sub(rf'\1"{value}"', tail, count=1) if entry.search(tail)
                else f'\nicu-10201 = "{value}"' + tail)
        block = head + tail
    else:
        block = block.rstrip("\n") + f'\nper_sensor_defaults."icu-10201" = "{value}"\n'
    return text[:lo] + block + text[hi:]


def cmd_set(args) -> int:
    queue = Path(args.queue).expanduser().resolve()
    if not queue.is_file():
        raise SystemExit(f"no such queue: {queue}")
    if not TOML.is_file():
        raise SystemExit(f"no toml at {TOML} — has setup_mac_py39.py been run?")

    backup = TOML.with_suffix(".toml.echoears-bak")
    if not backup.exists():
        shutil.copy2(TOML, backup)
        print(f"backed up original -> {backup.name}")

    text = TOML.read_text()
    TOML.write_text(_set_keys(text, str(queue)))
    print(f"[plugins.txrot] now points at {queue.name}\n")
    return cmd_status(args)


def cmd_restore(_args) -> int:
    """Undo every echoears edit by putting the original toml back."""
    backup = TOML.with_suffix(".toml.echoears-bak")
    if not backup.is_file():
        print(f"no backup at {backup} — echoears never edited this toml.")
        return 1
    shutil.copy2(backup, TOML)
    print(f"restored {TOML.name} from {backup.name}\n")
    return cmd_status(None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show which queue is live").set_defaults(func=cmd_status)
    s = sub.add_parser("set", help="point the plugin at a queue")
    s.add_argument("queue")
    s.set_defaults(func=cmd_set)
    sub.add_parser("restore", help="undo echoears' edits (put the original toml back)"
                   ).set_defaults(func=cmd_restore)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
