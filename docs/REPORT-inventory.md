# 汇报清单 — TA 之上做“驻留感知 + 自主搬迁”这一条线的全部证据

日期 2026-10-31　环境：昇腾 910B2 ×2（每卡 892 块 × 128 = 114,176 token）、Qwen2.5-14B-Instruct、真实 mini-swe-agent 负载（tm4 上跑，经隧道到昇腾）。

## 0. 一句话结论

**驻留感知的路由（把每个 program 钉在它 KV 所在的那张卡上）是有效且免费的；“主动搬迁”在可测的三类场景里都没有独立价值**——因为它的成本（capture+pull ≈0.4 s/次）与它能拿回的收益（重算 ≈0.28 s/次）同量级，而真正的问题在放置（谁被放到快满的卡上）。

## 1. 关键数字（按证据强度排序）

| # | 事实 | 数字 | 来源 |
|---|---|---|---|
| 1 | 亲和 vs 轮询（合成负载，6 轮） | 85.2% vs 53.0%（N=16/32/40 三点） | M3 |
| 2 | 亲和 vs 轮询（真实 agent，短查询） | 76.10% vs 44.58%（+31.5 pt） | M6 短查询 |
| 3 | 与裸 TA 头对头（2 卡，24/32 program） | 1.004×（不回归也不占优） | E5 |
| 4 | 与裸 TA 头对头（真实 agent，6 实例） | 96.34% / 400 s vs 96.86% / 535 s（TA 更快） | E11 |
| 5 | 32 program 压力档（三臂） | TA 81.96% / 3,940 tok/s；sticky 82.16% / 4,454；ta_like 81.81% / 5,207（单次） | E11 / E12c |
| 6 | 跨卡搬运可行（p2p） | 首次 token 0.226→0.139 s（1.82×） | M6-A |
| 7 | 搬运成本 vs 重算 | 0.41 s vs 0.28 s ⇒ 净 −0.13 s/次 | E3d / E5 更正 |
| 8 | 保活（1-token ping） | 存活 0/10 → 10/10，代价 3 倍 prefill，时延零收益 | M11 / E10-2 |
| 9 | prefill 占单步 | 0.5~2.8%（512 输出），decode 主导（~10 tok/s） | E10-1 |
| 10 | 容量拐点 | 6 program 95.8% → 32 program 82%（真实 agent） | E11 压力臂 |

## 2. 已经排除的假设（都做过实验）

| 假设 | 实验 | 结果 |
|---|---|---|
| 命中率低是因为“块被 LRU 清掉，而 program 还在回来” | M10 驻留实验（11 格） | 空窗 30 s 不掉；竞争一过 0.5× 容量全灭 ⇒ 是竞争不是时间 |
| 保活能救回来 | M11 / E10-2 | 能救命中率（0/10→10/10），但零时延收益、3 倍账单 |
| 搬迁能救回来 | E2 / E2-offpath / E10-3 | 能（0→98.5%），但只在“人为造超容 + 关掉正确放置”时有用；正常情况被放置支配 |
| prefill 是瓶颈 | E10-1 | 0.5~2.8%，不是 |
| TA 的容量记账是对的 | E10-4 | `kv_cache_usage_perc` 恒 0 ⇒ `shared_tokens` 抵消全部预算 ⇒ TA 永不节流（本平台特有） |
| 我们的 router 只要“亲和”就够 | E9 / E11 | sticky 无容量感知会把 program 钉到快满的卡（70.26% vs TA 75.38%） |

## 3. 现在这一版（`mod ta_like`）做了什么

- 容量账本：`held(card)=Σ program_tokens + 100×count`，容量取 `cache_config_info`；
- 先暂停后搬：`over/800 ≤ 2 s` 且该卡有在飞 → 挂在“有请求完成”事件上等（`asyncio.Condition`），不盲睡；
- 两卡都超容 → 立即放行并记 `over_admit`（等待造不出容量）；
- 只在目的卡剩余 ≥ 前缀时搬，搬完即写成路由事实。

## 4. 本次要交的 A/B（状态）

| 任务 | 状态 |
|---|---|
| 32 program × (TA vs ta_like) × n=3，每臂前重启两侧引擎 | **进行中**（后台 job `pwsh-8622b6224ab2439b`，日志 `data/e12d_sweep.csv`） |
| 16 program × 8000 词（≈1.3× 单卡 < 2× 单卡）×(TA vs ta_like) × n=2 | 已排在同一个 job 里，紧随其后 |

判据（预注册）：
- 32 program：ta_like 命中率 ≥ TA 且 tok/s ≥ TA（允许 ±0.5 pt 命中、±5% 吞吐视为持平）；
- 16 program：若两臂拉平 ⇒ +32% 来自 TA 在超容区的自我惩罚；若 ta_like 仍显著更快 ⇒ 是我们的设计。

装置细节（可复现）：两侧 `bash /root/e5/engine.sh` 重启引擎并断言 `num_gpu_blocks=892`；`bash /root/e5/arm.sh ta|like` 起对应路由（:9000 / :9004）；tm4 用 `cfg_c32_{ta,like}.yaml`（prefix_tokens 5000，slice 0:32，step_limit 6）与 `cfg_c16_*.yaml`（8000 词，slice 0:16）；采样走 ssh 直读引擎 `/metrics` 的 `prefix_cache_{queries,hits}_total` 差分。

## 5. 尚未完成 / 已知缺陷

1. n=3 的统计还没出来（job 在跑），目前所有“差距”都是 n=1。
2. `ta_like` 是**重实现**，不是给 TA 打补丁；TA 的 BFD 恢复、acting 衰减、分期、30 min 超时、`shared_tokens` 折算都未复刻 ⇒ 只能声称“容量口径一致”。
3. 未验证“TA 在环 + 搬家”（per-card 拓扑下 pin 被 TA 无视，需要给 TA 加 `program→instance hint` 接口）。
4. 本平台 decode 只有 ~10 tok/s（`--enforce-eager`），所以“命中率→时延”的换算被稀释；换 batch 化/图模式后结论可能反转。
5. TA 的 `kv_cache_usage_perc` 恒 0 是平台缺陷（E10-4），它让 TA 在本平台等于“不节流”；真实部署未必如此。
