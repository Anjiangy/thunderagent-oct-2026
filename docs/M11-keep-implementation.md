# M11 — 把 keep 接进 executor，并在真机上做 A/B

日期：2026-10-26　机器：升腾 910B2 单卡（device 0），容量 946 块 × 128 = 121,088 token
代码：`executor/keep.py` + `executor/app.py`（`keep_loop` / `_keep_once`）+ `executor/programs.py`（`record_refresh`）
测试：`tests/test_keep.py`（11 条门控测试）、`tests/bench_keep_e2e.py`（三段式 A/B）

---

## 1. 它做什么

executor 每 `EXECUTOR_KEEP_INTERVAL` 秒扫一遍 program 表，对**满足四道门**的 program 用**它自己的 prompt** 发一条 `max_tokens=1` 的请求。命中时只算几十个 token，但这次访问把它的块移到引擎 LRU 的头部——这是在我们不改 vLLM 的前提下，唯一能影响"谁继续驻留"的杠杆。

四道门（都在 `executor/keep.py::eligible` / `keep_candidates`）：

| 门 | 规则 | 为什么 |
|---|---|---|
| 大 | `prompt_tokens ≥ EXECUTOR_KEEP_MIN_TOKENS`（默认 2000） | 小前缀重算比保活便宜 |
| 会回来 | `requests ≥ EXECUTOR_KEEP_MIN_TURNS`（默认 2） | 只回来一次的 program 是净亏（M10 的盈亏分析） |
| 不占满 | `Σ 候选 prompt_tokens ≤ 65% × 集群容量` | 保太多就是把自己也拖进争抢 |
| 还活着 | `idle ≤ EXECUTOR_KEEP_TTL`（默认 900 s）、无 in_flight、非迁移中、实例健康 | 会话结束后继续刷就是白烧 |

排序是**按 prompt_tokens 从大到小**：省下的重算与前缀成正比，而占用的槽位与大小无关。

## 2. A/B 装置

`tests/bench_keep_e2e.py` 三段：

1. **settle**：10 个 program，各 3000 词（≈5.4k token）独立前缀，各跑 2 轮（让它们成为"会回来"的）；
2. **flood**：**绕过 executor**、直接打引擎 250k token 的无关流量（44 条，4 并发）—— 这样它们不会变成新 program，只做"挤人"；
3. **probe**：等 8 s，逐个发第 3 轮，前后读引擎 `/metrics` 差分。

三臂：keep 关、keep 2 s、keep 1 s。每臂重启 executor，引擎不重启。

## 3. 结果

| 臂 | 存活 | 命中率中位 | flood 墙钟 | 刷新次数 | 刷新计算量 | 单次均摊 |
|---|---|---|---|---|---|---|
| a-off | **0/10** | **0.0%** | 18.5 s | — | 0 | — |
| a-keep2 | **10/10** | **97.9%** | 19.6 s（+6%） | 139 | 114,468 | 823 |
| a-keep1 | **10/10** | **97.9%** | 19.8 s（+7%） | 187 | 123,689 | 661 |

（`data/m11_keep_e2e.csv`、`data/m11_keep_e2e.png`）

**存活是决定性的**：0/10 → 10/10。这不是"提升几个点"，是把整段上下文从"必然全灭"救回来。

## 4. 成本：比 M10 的理想值贵，原因是刷新也会 miss

M10 里干净的单次刷新只要 38 token；这里是 **823 token/次**（139 次共 114k）。差别不是实现问题，是**赛跑问题**：

- flood 的速率 ≈ 262k / 18.5 s ≈ **14k token/s**；
- keep 每 2 s 摸一次，两次触摸之间引擎塞进 ~28k token = **容量的 23%**；
- 于是刷新经常"晚到"：块已经被挤掉，这条刷新自己就变成一次 3k 的真实预填充。

把间隔缩到 1 s 只把均摊从 823 降到 661（+8% 的刷新次数换 −20% 的单次成本），存活不变——说明**间隔不是免费的旋钮**，它应该跟着 churn 走（这正是"四道门"里第 2 条要动态定间隔的原因）。

**吞吐代价**这一档只有 **+6%**（M10 是 +15~25%），因为这里 flood 是大请求、program 只占 45% 容量。

## 5. 盈亏账（诚实版）

- 收益：10 个 program 各回来一次 = 10 × 5.4k = **54k token** 不必重算。
- 成本：这 60 s 窗口里刷新自己算了 **114k token**（因为一半以上 miss），外加 6% 的 flood 变慢。
- ⇒ **在"只回来一次"的场景里，keep 是亏的**（114k > 54k）；**回来 2~3 次才转正**（3 次 = 162k 收益）。
- ⇒ 若能把均摊成本压到 M10 的 38 token（间隔跟着 churn 走、或只保命中率高的那些），一次回来就能赚。

这条账必须写进任何对外叙述里：**keep 不是免费的午餐，它是给"会回来的大会话"买的期权。**

## 6. 现状与下一步

已完成：门控实现 + 11 条单测 + 真机 A/B（0/10 → 10/10）。

未完成，按性价比排序：

1. **动态间隔**：用 `/metrics` 的 `prompt_tokens_total` 差分估 churn，令 `interval ≈ 分钟级容量 × 0.1 / churn`，目标是让单次刷新回到几十 token；
2. **按命中率自适应**：连续两次 miss 的 program 先降频（它已经在被挤，保它性价比低）；
3. **真实 SWE 流量 A/B**：工具等待 30~120 s、5~30 轮，正好是"回来多次"的形态，也是这套机制唯一可能真正赚的场景；
4. **和 TA 的 pause 联动**：TA 暂停时 `unregister` 了 program，executor 侧看不到"它还会回来"的信号；若把 TA 的 pause 事件透给我们，TTL 与门可以更准。

## 7. 复现

```bash
# 部署
tar -cf m11.tar executor tests && scp m11.tar root@<host>:/root/m11.tar
cd /root/m11/program-executor && tar -xf /root/m11.tar

# 起 executor（keep 开/关只差一个变量）
EXECUTOR_BACKENDS='a=http://127.0.0.1:8110' EXECUTOR_PLACEMENT=affinity \
EXECUTOR_BALANCE=off EXECUTOR_KEEP=on EXECUTOR_KEEP_INTERVAL=2 \
  nohup python3 -m uvicorn executor.app:app --host 127.0.0.1 --port 8100 &

python3 tests/bench_keep_e2e.py --label a-keep2 --programs 10 --prefix-words 3000 --flood-tokens 250000
```
