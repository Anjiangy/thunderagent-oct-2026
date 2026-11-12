# E9 修正版 Mod：sticky 放置把集群命中率抬到 79.79%

日期：2026-10-30　双卡 910B2（各 892 块 ×128 = 114,176 token）
负载：12 个 SWE 实例，前 6 个前缀 ×8（`MSA_HEAVY_N=6 MSA_HEAVY_MULT=8`），`--workers 12`，`slice 0:12`

## 三种放置的对照

| 臂 | 墙钟 | 集群 dq | 相对容量 | A/B 分布 | A hit | B hit | 集群 hit |
|---|---|---|---|---|---|---|---|
| 裸 TA（tr 路由） | 236 s | 210,626 | 0.92× | 43/57 | 78.50% | 75.66% | **76.88%** |
| Mod affinity（首见钉住） | 78 s | 185,246 | 0.81× | 88/12 | 73.24% | 79.59% | 74.00% |
| Mod sticky（按字节再评估） | 97 s | 182,548 | 0.80× | 21/79 | **98.54%** | 74.88% | **79.79%** |

## 结论

1. **sticky 比裸 TA 高 2.9 pt**（79.79% vs 76.88%），比 affinity 高 5.8 pt——这是这套东西里第一个正结果。
2. 机制很直接：sticky 把负载压到 21/79，A 卡只装 21% 的量，命中率因此到 **98.54%**（几乎全命中）；B 卡承担 79%、命中 74.88%。相比之下 affinity 把 88% 压到 A，A 立刻掉到 73.24%。
3. 也就是说：**收益来自“别把卡压满”，而不是“搬得多”**。A 卡轻载时命中率极高，这一部分收益足以抵消 B 卡较重带来的损失。

## 代码（这次可复现）

`mod/cli.py`（225 行，本地仓库）：三模式 `passthrough/affinity/sticky`；`estimate()` = `len(text)/3.6`、`actual` = 流式响应里的 `usage.total_tokens`；`load()` 取二者 max；sticky 的选择规则是 **"把自己从卡上减掉后再比"**：

```python
def effective(name):
    own = self.program_tokens(key) if current == name else 0
    return load[name] - own
best = min(names, key=lambda n: (effective(n), n))
```

即：如果一张卡之所以满，是因为这个 program 自己就在上面，那就不换——这避免了“程序被自己挤走”的抖动。只有另一张卡减掉自己后仍明显更轻（`effective(best) + est < effective(current)`）才移动，并 `moves += 1`。

单测 `tests/test_mod_placement.py` 9 个（估计量、max 语义、affinity 恒钉、sticky 装载分散、自我负载不搬、明确更轻才搬、passthrough 轮询、kill-switch、usage 正则），`pytest` 全过。

## 诚实边界

- **单次跑**：每格各 1 跑，没有重复；dq 也不同（210k / 185k / 183k），严格说不可直接并列。
- 墙钟仍不可比（引擎冷热、容器状态影响），上表只用 dq 与 hit。
- 该负载是**合成前缀**（长/短两档），不是真实 SWE 轨迹——真实轨迹下 prefix 长度差异小，收益可能缩水。
- 负载 0.80× 集群：两卡都没到容量线，sticky 的收益来自“把一张卡压到 21%”而非“避免越线”。

## 复现

```bash
# A 机
cd /root/mod && setsid nohup python3 -u cli.py --listen 9002 --mode sticky \
  --kill-switch /tmp/mod.kill --card a=http://127.0.0.1:8110 --card b=http://10.244.0.223:8110 \
  >/root/mod/sticky.log 2>&1 </dev/null &
# tm4
ssh -N -L 9000:localhost:9002 -p 31475 root@223.92.35.180 &
MSA_HEAVY_N=6 MSA_HEAVY_MULT=8 /home/agent-bench/env/ta/bin/python -m minisweagent.run.extra.swebench \
  -c src/minisweagent/config/extra/swebench_exec.yaml --split test --filter "$(cat filter_regex.txt)" \
  --slice 0:12 --redo-existing --workers 12
```
