# M12 — 改不改迁移：把 16 个 program 硬钉到一张卡，开/关迁移

日期：2026-10-26　双卡 910B2（各 946 块 × 128 = **121,088 token**），集群 242k
代码：`tests/bench_keep_roi.py`（）＋ executor 的 `/v1/programs/{pid}/seed`（强制落点）
数据：`data/m12_migration.csv`

## 为什么之前几次没测出迁移的价值

前几轮（M8 的 `fill`、M6 的 `skew`）都打算造“一张卡过热”，但都失败在同一个地方：

- `fill` 用 `kv_usage` 判断“这张卡满了没”，而**驱逐一发生 `kv_usage` 就掉回低位**——于是它以为卡还空着，继续往上钉；或者反过来把负载均匀铺开。
- 用 `--skew-frac` 依赖 bench 侧的 seed，但落点仍受 `assign()` 的容量门影响。

结果就是“人为倾斜”没真的倾斜：两卡 usage 1.33 / 1.33，`moves=0`，两臂数字一样。**这不是迁移无效，是场景没造出来。**

这一次改成：先用 `/v1/programs/{pid}/seed` 把 **16 个 program 全部硬钉到 a 卡**（约 144k token 需求 > 单卡 121k），集群总量 144k < 242k——即“a 卡装不下，但集群装得下”。这正是迁移唯一可能有用的形态。

## 结果

| 臂 | 搬家次数 | 每轮重算 token | 总重算 | 命中率 | 墙钟 |
|---|---|---|---|---|---|
| 迁移关 | 0 | 144k / 144k / 144k / 144k | **576,344** | **0.0%** | 255.0 s |
| 迁移开（skew） | **4** | 144k / 12.8k / 0.6k / 0.6k | **158,064** | **66.3%** | 207.1 s |

- **总重算 −72.6%**（576k → 158k），**墙钟 −19%**（255 → 207 s），命中率 0% → 66.3%。
- 平衡器只搬了 **4 个** program（`[bal] usage={'a':1.774,'b':0.592}`，hot 1.774 > 0.75、cold 0.592 ≈ 0.55、gap 1.18 ≫ 0.10）就把 a 卡从 1.77 倍需求压到可控，够了。
- 第二、三轮之后重算降到 **558 token**（≈ 三条请求的 prompt 元数据），说明搬迁之后前缀真的留在新卡上了。

## 结论

**该改（该迁移）**——在“热卡超容、集群有余”的形态下，迁移把 7 成的重算消掉了。这也把前面几份文档里“迁移不占优”的结论收窄成一句准确的话：

> 迁移不是普遍提速手段；它只在**热卡需求 > 单卡容量**且**集群仍有空余**时生效。工作集装得下时它无事可做，集群也装不下时它只是把重算搬到别处。

## 与 keep 的关系（两条不同的杠杆）

| | keep（M11/M11b） | 迁移（M12） |
|---|---|---|
| 适用形态 | 单卡、无空余卡可去 | 多卡、集群有余 |
| 机制 | 定期重发 prompt 保 LRU | 把 program 的 pin 挪到冷卡（recompute handoff） |
| 成本 | 常驻集 ÷ 间隔 的查找带宽，**在 11k tok/s churn 下净亏** | 每个被搬 program 一次 prefill |
| 实测 | 0/10 → 10/10 存活，但 ROI 为负 | **−72.6% 重算** |

两者不冲突：**有卡可去就搬（收益大、成本一次性），没卡可去才考虑保活（成本持续、只在低 churn 下划算）**。

## 复现

```bash
# 两卡引擎：8110(dev0) / 8111(dev1)，各 121k
EXECUTOR_BACKENDS='a=http://127.0.0.1:8110,b=http://127.0.0.1:8111' \
EXECUTOR_PLACEMENT=affinity EXECUTOR_BALANCE=skew|off EXECUTOR_KEEP=off \
  nohup python3 -m uvicorn executor.app:app --host 127.0.0.1 --port 8100 &

# 强制把 16 个 program 钉到 a 卡
for i in $(seq 0 15); do
  curl -s -X POST -H 'content-type: application/json' -d '{"instance":"a"}' \
    http://127.0.0.1:8100/v1/programs/<label>-p$i/seed
done
python3 tests/bench_keep_roi.py --label <label> --programs 16 --prefix-words 9000 \
  --turns 4 --gap 12 --no-flood
```
