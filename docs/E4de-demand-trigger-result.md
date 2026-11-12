# E4-de：demand 触发修好了，但 recompute 载体让 budget 对比失真

日期：2026-10-28　双卡（A:8110 本机 / B:10.244.1.219:8110），聚合 executor :8100

## 1. 触发信号换成 demand 后确实会触发

`_balance_once` 现在用 `_demand_ratio = Σ pinned prompt_tokens ÷ capacity`（本地构建早已改成 demand，服务器此前的旧副本用的是 `kv_cache_usage`）。20 个 program × 4,000 词（≈6.5k token/个，需求 130k > 单卡 114k）全钉 a 卡时：

```
[bal] usage={'a': 1.129, 'b': 0.06}    <-- 越过 hot=0.75
[bal] usage={'a': 1.069, 'b': 0.119}
[bal] usage={'a': 1.009, 'b': 0.179}
```

`usage` 是 demand/capacity，可以 >1（需求超过容量），这正是我们想要看到的"卡被压过线"。此前用 `kv_cache_usage` 时这个数是 0.06~0.18，永远碰不到 0.9。

## 2. budget 4 vs 8 的对比（各 1 跑，4 轮，20 program × 4000 词）

| 组 | 每轮 p50 | sum_p50 | 搬家次数 | 请求失败 |
|---|---|---|---|---|
| budget=4 | 2.34 / 2.34 / 2.32 / — | **9.335** | **15** | 4 次 HTTP 500（第 1 轮越线时） |
| budget=8 | 2.33 / 2.34 / 2.35 / 2.32 | **9.342** | **0**（本轮 `[bal]` 未扫描，B 侧健康检查在此期间不健康，`len(usable)<2` 提前返回） | 0 |

两臂 p50 差 0.007 s，在噪声内。

## 3. 为什么这组对比没有意义（装置缺陷，先记下来）

这一轮 `EXECUTOR_MODE=recompute`：**"搬一个 program" 的实现就是在目标卡重跑一次 prefill**。所以"搬"和"不搬"在做同一件事，budget 多少都不该改变总计算量 —— 测出来平是必然的，不是结论。

要测 budget，必须用 `MIGRATE_CARRIER=transfer`（真搬 KV）。但 transfer 载体在 N=16/WORDS=4000 那组会挂住（首轮 200 s 超时，两次尝试都 30 min 未收敛），原因是源卡此时已把块驱逐、capture 拿不到 kvp，每次搬家都在等超时。

## 4. 下一步（一次跑完的方案）

1. 把 `MIGRATE_FALLBACK` 设成 `none` 并按 `capture_ms` 设 3 s 硬超时，避免搬家拖死请求；
2. 用 N=12 / 3000 词（需求 78k，压在 0.68×，不驱逐）跑 budget 2/4/8 —— 这样 capture 一定拿得到 kvp，才能干净比较"搬多少"；
3. 若那时 budget 8 明显优于 2，则定额按需求算成立；否则定额这一支折算为单点计算。

## 数据

`/root/e2/log/r2_4.log`、`/root/e2/log/r2_8.log`、`/root/e2/e4d.py`（bench，注意 `json.dumps(..., flush=True)` 是错的，要 `print(..., flush=True)`）。
