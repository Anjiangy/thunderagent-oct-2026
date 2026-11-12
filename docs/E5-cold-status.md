# E5 冷启动错配格：装置已就绪，真机未跑通

## 想量什么

TA 只能看到"每张卡还剩多少 KV 容量"，看不到"某个 program 的上下文其实已经在哪张卡上"。
于是当 KV 已在 B、TA 只按剩余容量把请求排到 A 时，A 要整段重算。

两臂的差 = **"知道 KV 在哪"这件事值多少**，也就是一次搬迁决策最多能买到的东西。

| 臂 | 做法 |
|---|---|
| `free` | 一半 program 的 KV 预热到 A、一半到 B，然后让 TA 完全自由分配 |
| `pin` | 同样预热，但把每个 program 钉回"KV 所在的那张卡" |

## 装置

`tests/e5cold.py`（已入库）：16 program × 5000 词（≈9k token，两卡各 8×9k = 72k，均未越线）；
预热走后端 executor，正式 8 轮走 TA；每轮记 p50，最后输出 `per_turn_p50` / `sum_p50`。

## 现状（2026-10-28）

- `free` 臂第一次跑在 turn1 全部请求失败（`e5cold.py` 抛 `no median for empty data`），
  随后对 TA 的单条探针请求**超时 180 s**——TA 进程已挂，不是脚本问题。
- 因此**这一格还没有数据**。上一轮 `ta_percard` 能正常跑到 47.1 tpm，说明装置本身可用；
  这次是运行态问题（TA 长时间带状态运行 + 多次 pkill 后残留）。

## 恢复步骤（下次直接照做）

```bash
# 1) 清干净（两边都做）
pkill -9 -f 'uvicorn executor.app'; pkill -9 -f ta_launch; pkill -9 -f ThunderAgent
# 2) 起两个单卡 executor
cd /root/m11/program-executor
EXECUTOR_BACKENDS="a=http://127.0.0.1:8110"  nohup python3 -m uvicorn executor.app:app --port 8101 &
EXECUTOR_BACKENDS="a=http://<POD-D-POD>:8110" nohup python3 -m uvicorn executor.app:app --port 8102 &
# 3) 起 TA（两后端）
cd /root/m2 && PYTHONPATH=/root/m2:/root/m2/src nohup python3 ta_launch.py \
  --backends http://127.0.0.1:8101,http://127.0.0.1:8102 --port 9000 &
# 4) 两臂
ARM=free N=16 WORDS=5000 TURNS=8 GAP=6 python3 tests/e5cold.py
ARM=pin  N=16 WORDS=5000 TURNS=8 GAP=6 python3 tests/e5cold.py    # 前需重启 TA
```

## 预注册判据

- `free` 臂的 A/B 命中比应显著不均（说明 TA 确实把有 KV 的 program 排错了卡）；
- `pin` 臂 `sum_p50` 比 `free` 低 ≥10% 才算"错配代价真实"；
- 若两臂差 <5%，说明 TA 的容量均衡本身已经接近最优，这条路线在 evict-vs-migrate 上确实没有优势。
