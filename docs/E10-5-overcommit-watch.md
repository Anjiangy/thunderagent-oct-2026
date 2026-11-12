# E10-5 — 可判定检测：TA 是否在"看不见成本"的情况下超发

工具：`tools/ta_overcommit_watch.py`（纯 stdlib，可用 `--duration/--interval/--window` 以 cron 或 CI 方式跑；退出码 2 = 有告警）。

## 判据

| 量 | 含义 |
|---|---|
| `intended` | TA 自认的上下文占用 = `Σ /programs[*].total_tokens`（**不是** `/health.per_backend.total`，那是 program 个数） |
| `reported` | 引擎自认的占用 = `kv_cache_usage_perc × (block_size × num_gpu_blocks)` |
| `fill` | `intended / capacity` |
| `coverage` | `reported / intended` |

判定（需连续 `--window` 个 tick 一致才算数，默认 3）：

- **BLIND_OVERADMIT**：`running > 0` 且 `reported ≈ 0`（引擎有请求在跑却说零占用）；或 `fill ≥ 0.60` 且 `coverage < 0.25`（TA 认为大部分在缓存里）。
- **TIGHT_NO_PAUSE**：`fill ≥ 0.90`、`coverage ≥ 0.75`、且 `paused == 0`（真的快满了却没人暂停）。
- 其它 = OK。

## 真机验证（单卡 114,176；TA(tr) → 一张卡；8 个 program × 6000 词 ≈ 9.1k token）

| 指标 | 值 |
|---|---|
| 采样 tick | 90（每 2 s 一次，window=3） |
| 判定分布 | **BLIND_OVERADMIT 88 / OK 2** |
| 峰值 fill | **0.944**（intended 107,796 / 114,176） |
| 峰值 coverage | **0.000**（引擎报告占用 0） |
| 告警行 | 88 |

即：TA 已经接纳了 94% 容量的上下文，而引擎侧报告"一块都没占用"——按 TA 自己的公式 `shared_tokens = Σreasoning − kv_cache_usage×容量`，它会认为这些上下文全部已在缓存、后续请求几乎免费，于是继续接纳，直到把卡打穿。

## 两个必须写明的边界

1. **本机的 `reported` 恒 0 有两层原因**：该引擎实例请求结束即释放块（无 prefix caching 保留），以及采样点多落在请求之间（`running=0`）。两条都会让 `coverage` 归零，因此检测报的是"TA 的视野缺失"，不是"必然已压穿"。
2. 因此工具的语义是**预警**：`coverage` 长期接近 0 而 `intended` 已高 ⇒ TA 的容量账失去锚点。健康部署里 `coverage` 应接近 1（前缀缓存保留块 + 指标正确上报）。

## 用法

```bash
python tools/ta_overcommit_watch.py \
  --ta http://127.0.0.1:9001 --engines http://127.0.0.1:8110 \
  --interval 2 --window 3 --duration 300 --jsonl /root/e10/watch.jsonl
# 退出码 0 = 未发现盲超发；2 = 发现（可接告警/CI）
```

多卡时 `--engines` 传逗号分隔的多个引擎地址；工具按 TA `/programs` 里每个 program 的 `backend` 字段分卡汇总。

## 产物

`tools/ta_overcommit_watch.py`、`tests/test_ta_overcommit.py`（8 个纯逻辑单测，全部通过）、`scripts/drive_programs.py`（打流用）。