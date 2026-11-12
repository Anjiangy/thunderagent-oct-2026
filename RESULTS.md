# 十月结果总览

按时间顺序列出每个实验、结论与原始数据位置。所有数字都能在 `data/` 的对应 CSV 或 `docs/` 的文档里找到出处。

## 0. 图 5 复现（10-16 ~ 10-17）

`fig5/fig5_msa_results.csv` · 图：`fig5/fig5_msa_reproduction.png`

| N | roundrobin 命中 | single(TA) 命中 | rr step/min | TA step/min |
|---|---|---|---|---|
| 24 | 50.06% | 80.49% | 17.2 | 27.8 |
| 48 | 6.61% | 77.36% | 27.1 | 26.2 |
| 72 | 2.85% | 70.89% | 26.5 | 34.7 |
| 93 | 1.99% | 60.33% | 30.6 | 40.7 |

结论：轮询把前缀打散，命中率随并发单调塌陷到个位数；程序亲和把它锁在一张卡上，命中率维持在 60% 以上，step/min 在高并发反超。**N=48 是唯一 TA 略慢的点**（27.1 vs 26.2），原因是该点两臂都还没真正越容量。

## 1. M1–M2：executor 与控制器接通（10-23）

- `docs/M1-result.md`、`docs/M2-result.md`
- 结论：program → 固定后端的路由层可用；初始化成本（首轮 miss）必须在分析里显式扣掉。

## 2. M3：亲和剂量-反应（10-23）

- `docs/M3-result.md`、`data/m3_*.csv`

| N | 亲和 | 轮询 | 亲和 p50 | 轮询 p50 |
|---|---|---|---|---|
| 16 | 89.5% | 83.3% | 1.90 s | 1.91 s |
| 32 | **81.3%** | **60.1%** | 1.96 s | 4.78 s |
| 40 | **85.5%** | **53.0%** | 1.95 s | 6.15 s |

结论：N=16 时两卡各装 73.7K（< 114K），亲和没有额外价值；越过容量线后轮询每卡 184K（超 61%），命中率与尾延迟同时恶化。

## 3. M4：预热式交接（10-25）

- `docs/M4-result.md`、`docs/M4-compare-result.md`
- 结论：迁移前先把目标卡预热，迁移后的首次请求命中率 0.9682 / 0.9695 / 0.9726（三次），而"只改 pin 不预热"的控制臂是 0.000。

## 4. M5：三臂对照（10-24 ~ 10-25）

- `docs/M5-result.md`、`docs/M5-three-arm-and-n40.md`
- 结论：裸 TA / 亲和 / sticky 三臂命中打平（85.7% / 85.7% / 85.9%）；**N=40 时我们的臂 park**，暴露"聚合口径让 TA 看不见单卡上限"的问题（见 E5）。

## 5. M6：p2p 搬运与压力窗口（10-25）

- `docs/M6-full-report.md`、`docs/M6-A-p2p-transfer-result.md`、`docs/M6-pressure-window.md`
- p2p 交接：TTFT **0.228 / 0.197 / 0.196 s → 0.118 / 0.110 / 0.113 s（1.82×）**
- 三臂总量（40 program，8 轮）：bare TA 81.6% / recompute 81.1% / transfer 79.7% —— **搬不如重算**
- 压力窗口（热卡 0.95）：7.38% → 49.98%（KV pull）/ 54.39%（recompute），13 次搬迁

## 6. M7–M9（10-26）

- `docs/M7-real-traffic-ab.md`、`docs/M8-2x2-result.md`、`docs/M9-design-framework.md`
- 2×2（放置信号 × 是否搬家）：A 轴为空（85.73 vs 85.69），B 轴 moves=0 ⇒ 均匀铺卡时搬运根本不触发。

## 7. M10–M11：驻留与保活（10-26）

- `docs/M10-residency-report.md`、`docs/M11-keep-implementation.md`、`docs/M11b-keep-roi.md`
- 空窗 30 s 仍 99.29% ⇒ **不按时长驱逐**；200k/400k churn 一到 ⇒ 0/10 ⇒ 淘汰由流量体积决定
- keep（每 2 s 一个 1-token 刷新）⇒ 10/10，代价 filler 单条墙钟 0.78 → 0.91~0.98 s（+15~25%）
- 端到端 ROI 为负：keep 873k vs 不 keep 955k 的重算量，但账单 3×

## 8. M12 / M12b：搬迁决策与数量（10-26）

- `docs/M12-migration-decision.md`、`docs/M12b-move-sweep.md`、`data/m12_move_sweep.csv`

| 搬迁预算 | 实际搬家 | 总重算 | 命中 |
|---|---|---|---|
| 0 | 0 | 576,344 | 0.0% |
| 2 | 2 | 418,180 | 20.0% |
| **4** | 4 | **163,696** | **65.1%** |
| 6 | 6 | 167,024 | 64.3% |
| 8 | 8 | 163,696 | 65.1% |

结论：边际收益在第 3~4 个最大（127k/个），**第 5 个起为 0**；应搬 `ceil((D−K)/p̄)` 个，不是"能搬就搬"。

## 9. E1–E5：KV 策略的定量边界（10-27 ~ 10-28）

- `docs/E1-q-surface.md`、`docs/E2-report.md`、`docs/E3-cost-model.md`、`docs/E4-report.md`、`docs/E5-corrected-result.md`
- **E1 悬崖**：0.40× 容量时命中 0.98，**0.50× 直接 0.00** —— 不是衰减，是断崖
- E2 双向：0 → 98.5%；离径预备把最差一步 10.72 s 压到 1.32 s
- E3 目的地质量：搬入后存活与目的地当时负载无关（余度 1.0/0.75/0.5/0.25 全 0.977）；生死由搬完后的累计 churn 决定
- E4 时机门：四类门（中位数/最长间隔/p75/定额）只有"定额"有效
- **E5 正确接法**：聚合口径 → 0.73×；per-card executor → **1.004×**（47.1 vs 46.9 tpm）

## 10. E6–E9：真实 SWE-agent（10-29 ~ 10-30）

- `docs/E6-clean-pair.md`、`docs/E9-result.md`、`docs/E9-sticky-result.md`
- E6 干净配对：18 实例，命中 76.5% vs 77.4%（噪声内），墙钟受尾部效应主导
- E9：三臂 96.34 / 96.86 / 97.11%，但**并发上限被实例数卡在 6**，KV 只到 0.41
- **sticky 在真实短会话上明显更差**（70.26% vs 75.38%）

## 11. E10–E11：为什么"看不见收益"（10-30）

- `docs/E10-1-prefill-share.md` ~ `E10-5-overcommit-watch.md`、`docs/E11-real-sweep.md`、`docs/E11-pressure.md`
- prefill 只占单步 **0.5~2.8%**（512 输出），单步由 decode 主导（9~11 tok/s）⇒ 所有 KV 收益都被压缩
- TA 的 `context_len` 是字符估算、偏高 3.4~5.2×；真正缺陷是 `shared_tokens` 依赖恒 0 的 `kv_cache_usage_perc` ⇒ 永不节流
- **E11 压力臂**：32 program 时命中 95.82% → **82.16%**（裸 TA 81.96%），这是真实 agent 流量上"高并发→命中下降"的唯一证据

## 12. E12–E13：TA-like 与 mod 的由来（10-31）

- `docs/E12-ta-like.md`、`E12b`、`E12c`、`docs/M13-TA-patch-plan.md`
- 把"暂停优先、迁移其次"的策略抽成纯函数（`mod/policy.py`），并用 32 program 的负载验证；
- `mod/cli.py` 是它的 HTTP 外壳（三模式 + kill switch）。

## 数据字典

- 命中等百分比一律是引擎计数器差分：`hits_total / queries_total`；
- `step/min` 是客户端侧完成步数除以墙钟，跨臂比较时需注意墙钟受工具执行时间主导（见 `docs/E12d-harness-incident.md`）；
- CSV 中 `salt` 列表示该轮使用的 prompt 前缀盐值，用于保证两臂冷启动条件一致。