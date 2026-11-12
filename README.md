# ThunderAgent 复现 + KV 迁移实验（2026 年 10 月）

这是 2026 年 10 月组会申报的两件事的**原始结果、文档与正式 mod**：

1. **ThunderAgent 图 5 复现**——在昇腾双卡 910B2 上，用 mini-swe-agent 作负载，比较
   "轮询负载均衡（vLLM）" 与 "程序亲和（ThunderAgent `tr` 模式）" 的 prefix-cache 命中率与吞吐；
2. **KV 迁移实验（M1–M13 / E1–E12）**——在 ThunderAgent 之上做 program 粒度的放置、暂停/恢复、
   预热式交接（recompute handoff）、p2p 搬运与驻留/保活，量清楚"什么时候搬有收益、什么时候没有"。

> 11 月的 KV park / host 常驻（`_kv_park`、E49/E50 等）**不在本仓库**，按老师要求另行归档。

## 一页结论

| 实验 | 结论 | 关键数字 |
|---|---|---|
| 图 5 复现 | 高并发下轮询的命中率塌到个位数，亲和维持在 60%+，吞吐同步反超 | N=93：**1.99% vs 60.33%**；step/min **30.6 vs 40.7** |
| M3 亲和剂量-反应 | 亲和只在"单卡工作集越容量"时才付钱 | N=32：81.3% vs 60.1%；N=40：85.5% vs 53.0% |
| M5 三臂对照 | 三臂命中打平，差异在噪声内 | 85.7% / 85.7% / 85.9% |
| M6 p2p 交接 | 跨卡搬运能把首 token 时延砍掉近一半 | TTFT **0.228 → 0.118 s（1.82×）** |
| M10–M11 驻留/保活 | 空窗不驱逐、竞争才驱逐；保活能救命中但要付 15~25% 时延 | 空窗 30 s 仍 99.29%；churn 一到 0/10；keep 后 10/10 |
| M12b 搬迁数量 | 边际收益在第 4 次归零，应"搬刚好够" | 重算 576,344 → **163,696**（4 次） |
| E1 KV 悬崖 | 命中不是缓慢衰减，是断崖 | 0.40× 容量 0.98 → **0.50× 0.00** |
| E5 正确接法 | 聚合口径会让 TA 看不见单卡上限，改 per-card 后回到打平 | 34.1 → **1.004×**（47.1 vs 46.9 tpm） |
| E9 sticky | 每步重算放置反而更差 | 70.26% vs 75.38% |
| E11 真实 SWE | 真实 agent 流量下并发被实例数卡住；加压后命中才下降 | 96.3/96.9/97.1%；32 program：**95.82% → 82.16%** |

完整数字与逐实验文档见 [`RESULTS.md`](RESULTS.md) 与 `docs/`。

## 仓库结构

```
fig5/          图 5 复现的原始 CSV、图与绘图脚本
RESULTS.md     十月结果的汇总表（每条都指向 docs/ 里的原始文档）
docs/          95 篇实验文档（M1–M13、E1–E12、方法学与结论）
data/          93 个原始 CSV（每次跑的逐条记录）
scripts/       51 个实验脚本（bench / probe / plot）
mod/           ★ 正式 mod：program 放置与容量的策略层 + CLI（见 mod/README.md）
reports/       代码走读与对比报告（vllm-workflow-aware-serving、restructure 对比）
```

## 图 5 复现怎么做

负载：mini-swe-agent 跑 SWE-bench-lite 实例，每个实例是一个 program（`program_id` 由
`job_id` 注入），并发 N ∈ {24, 48, 72, 93}，两臂各跑一遍：

- `roundrobin`：请求轮询发到两张卡（等同普通 LB）；
- `single`：ThunderAgent `tr` 模式，program 钉在首次落到的卡上。

命中率取自引擎 Prometheus 计数器差分：`vllm:prefix_cache_hits_total / vllm:prefix_cache_queries_total`。
原始数据在 `fig5/fig5_msa_results.csv`，重绘：`python3 fig5/plot_fig5_msa.py`。

| N | 轮询 命中 | 亲和 命中 | 轮询 step/min | 亲和 step/min |
|---|---|---|---|---|
| 24 | 50.06% | 80.49% | 17.2 | 27.8 |
| 48 | 6.61% | 77.36% | 27.1 | 26.2 |
| 72 | 2.85% | 70.89% | 26.5 | 34.7 |
| 93 | 1.99% | 60.33% | 30.6 | 40.7 |

## 正式 mod（`mod/`）

一个**独立可跑**的 HTTP 服务，把 ThunderAgent 的"程序放置 + 容量记账"抽出来做成可插拔的策略层：

- 三种模式：`passthrough`（轮询、无记忆）、`affinity`（首次落点钉住）、`sticky`（每次重估，
  只在"不是自己把卡占满"时才移动——用减法做滞回）；
- 负载按 token 记账：`max(估算 len(text)/3.6, 实测 usage.total_tokens)`，与上游常量
  `BUFFER_PER_PROGRAM=100` 对齐；
- 带 **kill switch**，可以在不重启的情况下退回 passthrough。

用法见 [`mod/README.md`](mod/README.md)。策略核心 `mod/policy.py` 不依赖任何 Web 框架，可单测。

## 复现环境

- 昇腾 910B2 ×2，单卡 892 块 × 128 = 114,176 token KV 容量；Qwen2.5-14B-Instruct，
  `--enable-prefix-caching --enforce-eager --max-model-len 32768`；
- vLLM 0.23 + vllm-ascend；ThunderAgent（上游 0.1.0 语系）；
- Python 3.12；`httpx`、`fastapi`、`psutil`。

## 声明

- 所有数据均为真机跑出，CSV 里保留了当次运行的原始计数；个别文档标注了"作废/被推翻"的中间结论，
  这是过程记录，不删改。
- 未包含 11 月的 KV 常驻工作、未包含内部集群地址与凭据。