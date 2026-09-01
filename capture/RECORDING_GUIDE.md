# Recording guide — demo material (what each shot records, and how much)

**Layout**: one launcher per shot (`record_*.py`); the machinery lives in `_engine.py`.
**Flow**: board plugged in → `run/2_apply_queue.py` done once (the engine hard-stops
otherwise) → set up the physical scene → open the matching `record_*.py` and click
▶ Run → Enter → 3-2-1 → perform. The engine handles the rest: py39 re-exec, queue
check, bring-up, backlog drop, timestamped output, manifest append, and it prints
the replay/export commands afterwards. **No constants to edit.** More takes = more
clicks; nothing is ever overwritten.

Output: `out/capture/<label>_<time>.npz` + `out/capture/manifest.json`.

---

| Shot | File | Length | Setup | During | Purpose | Takes |
|---|---|---|---|---|---|---|
| Empty scene | `record_empty.py` | 15 s | clear 1.5 m, step aside | hold still | noise baseline / sigma control | 1-2 |
| **Hand push-pull** | `record_hand.py` | 40 s | palm at the right sensor (id 2) | 1 m↔20 cm slow ×3-4, last 10 s fast | **main offline-demo material** | 2-3, keep the best |
| Two-hand duet | `record_duet.py` | 30 s | left hand on id 3, right on id 2 | independent push-pull, offset rhythms | binaural-separation evidence | 2 |
| Walk-up | `record_walk.py` | 20 s | 2 m open lane | 2 m→0.5 m, pause 1 s, back; ×2 | full-body contrast | 1-2 |
| Door (optional) | `record_door.py` | 20 s | a door inside range | open, close once; body out of beam | listening-quiz material | 1-2 |
| **Two objects** | `record_chord.py` | 30 s | hard faces at 40 + 90 cm | still 10 s → slide the near one 40↔60 | polyphony + both listening modes | 2 |
| Crossing | Crossing (rangefinder) | `record_cross.py` | 20 s | clear lane, ~1 m out | far-left to far-right, pause, back; two passes | binaural showpiece **recorded under the run/10 Short Range preset** — replay/export with the --odr the engine prints (6) | 1-2 |
| Material | `record_material.py` | 30 s | a marked spot at 60 cm | book 10 s → empty 5 s → sweater 10 s | quiz material | 1-2 |

---

Afterwards (the engine prints these too):

```bash
# listen back (no hardware)
~/Documents/GitHub/ultrasonic/.venv-py39/bin/python apps/live.py --replay out/capture/hand_<time>.npz --odr 4

# export into the web offline demo
~/Documents/GitHub/ultrasonic/.venv-py39/bin/python tools/export_web.py out/capture/hand_<time>.npz --odr 4 -o web/data/hand233 --title "Hand sweep"
```

⚠ House rule: never touch the sensor mount mid-take — moved geometry voids the
take; re-record instead.
