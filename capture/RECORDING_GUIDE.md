# 录制指南 — 演示素材(每个文件录什么、录多少)

**目录**:每个镜头一个启动器 `record_*.py`;引擎机器在 `_engine.py`。
**通用流程**:板子插好 → 先跑过 `run/2_apply_queue.py`(233 cm 队列,引擎会硬拦)→
摆好物理场景 → 打开对应 `record_*.py` 点编辑器右上角 ▷ → 按 Enter → 3-2-1 → 做动作。
引擎自动完成:py39 切换 / 队列校验 / 起板 / 积压丢弃 / 带时间戳落盘 / manifest 追加 /
打印回放与导出命令。**不用改任何常量。** 多录几遍 = 多点几次 ▷,永不覆盖。

输出:`out/capture/<label>_<时间>.npz` + `out/capture/manifest.json`。

---

| 镜头 | 文件 | 时长 | 物理 | 录时 | 用途 | 建议遍数 |
|---|---|---|---|---|---|---|
| 空场景 | `record_empty.py` | 15 s | 前方 1.5 m 清空,人离开 | 静置不动 | 噪声基线/σ 对照 | 1-2 |
| **单手推拉** | `record_hand.py` | 40 s | 手掌对右传感器(id 2) | 1 m↔20 cm 慢速 3-4 回合,末 10 s 快挥 | **离线 demo 主素材** | 2-3,选最好的 |
| 双手二重奏 | `record_duet.py` | 30 s | 左手对 id 3,右手对 id 2 | 两手独立推拉,左慢右快 | 双耳分离证据 | 2 |
| 走近走远 | `record_walk.py` | 20 s | 留 2 m 走道 | 2 m→0.5 m 停 1 s→退,×2 | 大目标对照 | 1-2 |
| 开关门(可选) | `record_door.py` | 20 s | 量程内有门/柜 | 开、关一次,余不动 | 听力测验素材 | 1-2 |
| **双物体** | `record_chord.py` | 30 s | 硬面物 ×2 立于 40/90 cm | 静 10 s → 近者滑 40↔60,远者不动 → 静 5 s | 复音 + 两种听法对照 | 2 |
| 左右横穿 | `record_cross.py` | 20 s | ~1 m 处留左右空间 | 最左↔最右各一趟,中停 2 s | 双耳声像招牌 | 1-2 |
| 材质对比 | `record_material.py` | 30 s | 60 cm 定点做记号 | 硬书 10 s → 空 5 s → 毛衣 10 s | 测验题库 | 1-2 |

---

录完的下一步(引擎每次也会打印):

```bash
# 试听回放(无硬件)
~/Documents/GitHub/ultrasonic/.venv-py39/bin/python apps/live.py --replay out/capture/hand_<时间>.npz --odr 4

# 导出到网页离线 demo
~/Documents/GitHub/ultrasonic/.venv-py39/bin/python tools/export_web.py out/capture/hand_<时间>.npz --odr 4 -o web/data/hand233 --title hand
```

⚠ 房规同 ultrasonic 库:录制中途别碰传感器支架 —— 几何变了这条就作废,重录。
