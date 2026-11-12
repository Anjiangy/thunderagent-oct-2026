# E4dg：把门提到 demand≥1.0 之后，18×3200 的负载已经打不到门了

日期：2026-10-28　后端 A `127.0.0.1:8110`（kv_both 14579）/ B `<POD-G-POD>:8110`（kv_both 14580）
gate：`HOT=1.0`、`COLD=0.55`、新增 `EXECUTOR_BALANCE_EVICT_RATIO=0.90`（热卡 hits/queries > 0.90 就不搬）
负载：18 program × 3,200 词（需求 94k = 0.857×单卡容量），4 轮，每臂 3 次

## 结果（9 跑，全部 0 次搬家）

| budget | run1 | run2 | run3 | 中位 | 搬家 | a 卡 demand |
|---|---|---|---|---|---|---|
| 2 | 8.391 | 7.941 | 6.546 | **7.941** | 0 | 0.857 |
| 4 | 7.040 | 6.556 | 6.623 | **6.623** | 0 | 0.857 |
| 8 | 7.143 | 6.680 | 6.662 | **6.680** | 0 | 0.856 |

三臂中位 6.62 / 6.68 / 7.94，差异主要来自首跑引擎冷态（budget=2 的 run1/run2 明显偏慢），**与 budget 无关**。

## 为什么全是 0 次搬家

`usage` 是 demand/capacity，18×5.2k/114k = **0.857 < HOT=1.0** ⇒ 门根本没开。新增的 eviction 门（`no eviction ...` 计数也都是 0）同样没被走到，因为它在 demand 门之后。

要真正触发，需要 **demand > 1**：
- 23 program × 3,200 词 ≈ 120k（1.05×）；
- 或 18 program × 4,000 词 ≈ 130k（1.14×，但该配置此前出现过请求超时）。

## 结论

1. **“把门提到 1.0”这个动作是对的**——它把 0.86 这种“看着满但没超”的伪触发彻底关掉了（对照上一轮 budget=2 白搬 7 次）。
2. **但代价是这组负载不再触发**，所以定额仍未验证。要验证必须把需求抬到 1.0 以上。
3. 上一轮（HOT=0.75）budget=2 搬 7 次反而最慢（7.015 vs 6.555），这一轮（HOT=1.0）三臂全不搬且差异消失——两轮合起来正好说明：**在 0.86 附近，搬是纯亏损**。

## 复现

```bash
EXECUTOR_BALANCE_HOT=1.0 EXECUTOR_BALANCE_EVICT_RATIO=0.90 \
EXECUTOR_BALANCE_MOVE_BUDGET=$B EXECUTOR_MODE=kv EXECUTOR_MIGRATE_CARRIER=transfer \
BUD=$B N=18 WORDS=3200 TURNS=4 python3 /root/e2/e4d.py
```
