# run/ — click to run

Open any script here in VS Code and hit **▶ Run** (top right). No commands to
type, no flags to remember; press **Enter** through the prompts for defaults.

The interpreter re-execs into `ultrasonic/.venv-py39` by itself (the EVK
driver stack is py3.9), so it does not matter which Python opens the file.

| Script | What it does | Hardware? |
| --- | --- | --- |
| `1_listen.py` | Binaural listening (terminal), 233 cm, two sensors, 19.2 Hz | ✅ |
| `2_apply_queue.py` | Install the 233 cm meas queue | — |
| `3_queue_status.py` | Which queue is active + its range | — |
| `4_replay.py` | Run the same audio pipeline from a recording | ❌ |
| `5_show_recording.py` | Inspect a recording's range profile (ASCII) | ❌ |
| `6_plan_queue.py` | Plan any range — calculates, writes nothing | — |
| `7_test.py` | Unit tests (79 tests) | ❌ |
| `8_web.py` | **Live listening in the browser**: server + bridge + browser, one click | ✅ |
| `9_rangefinder.py` | **Vendor rangefinder firmware**: gpt + Long Range + TX Opt, 2 pulse-echo channels, on-chip targets | ✅ |
| `10_rangefinder_cfg.py` | Same, but **switch preset**: Short Range (near-field / palm-friendly), Static Target Rejection, factory default | ✅ |

**Recording demo material** → the [`capture/`](../capture/RECORDING_GUIDE.md)
folder: one `record_*.py` launcher per shot (empty / hand / duet / walk / door /
two-object / crossing / material). Click ▶ to record; click again for another take.

## Common flows

**First time** → `2_apply_queue.py` to install the queue → `1_listen.py` with
headphones.

**No board at hand** → `4_replay.py`.

**Sound seems wrong / want to see the data** → `5_show_recording.py`.

## Hardware and range

echoears has a single capture configuration: the **two-sensor temple pair**
(ids 2 and 3), 4 channels, **233 cm** (pulse-echo), ODR 4, 302 samples
(0.78 cm/bin), **TX 160 cycles**, **19.2 Hz**.
TX sets the energy budget (16 cycles left everything past 65 cm in the noise;
160 cycles measured +9 dB and real echoes to ~1.2 m); the RX window sets the
range axis; the part's physical ceiling is 1.7 m for a wall, 1.1 m for a post.
RX opens 0.9 ms after TX onset, so the axis starts at ~16 cm; closer targets
are range-ambiguous (they pile into the first bin), not invisible.

Two sensors instead of three buy two things: one fewer TX slot per rotation
(25.6 → 38.5 Hz budget) and half the readout, which is what makes ODR 5
possible and doubles range resolution versus the three-sensor rig.

> If the sensors on the board do not match the configuration, the launcher
> says which config to use — it does **not** reset the hardware. A reset
> cannot conjure a missing sensor, and repeated resets wedge healthy boards.

Range is set by the RX instruction's listening time; ODR only decides how many
samples that window is cut into (340-sample IQ buffer cap). For other ranges,
plan first with `6_plan_queue.py`.

> Archived recordings were captured at ODR 6 — `4_replay.py` /
> `5_show_recording.py` default to 6 for them; the axis follows the file.

## When the board will not come up

`TX-MUTED` / `LINK-DEAD` are known transients on this board and are **handled
automatically**: a failed bring-up runs the upstream recovery ladder (API
reset → soft reset → LDO power-cycle), then retries, 3 attempts by default.

Only when the ladder itself reports no response is it your turn — that is the
one case that needs a physical USB replug. To change attempts:
`apps/live.py --attempts N`.

## Undoing the upstream edit

`2_apply_queue.py` edits the EVK plugin registry (`PysonicPlugins.toml`);
the original is backed up. To restore completely:

```
python tools/use_queue.py restore
```

The upstream matrix pipeline assumes its own 22 cm queue when recording npz
(`matrix/frames.py` hardcodes `SMCLK_PER_SAMPLE = 32`), so run restore before
going back to that setup.

## Choosing between run/8 and run/9

The ICU-10201 has **one algorithm slot**, so the two are mutually exclusive:

| | run/8 (txrot) | run/9 (vendor gpt) |
| --- | --- | --- |
| Channels | **2×2 = 4** (incl. cross PC) | 2 (pulse-echo only) |
| Detection | host-side (our sigma gate) | **on-chip** (vendor absolute threshold) |
| Still objects | fade in 2.6 s ("what changed") | **keep reporting** ("what is there") |
| Sequence | our 233 cm queue | vendor Long Range |
| Near field | per-bin noise normalisation | ringdown_cancel + 8-segment threshold |

Switching is automatic: each script flashes the firmware it needs at startup.
Run run/8 and txrot is back.
