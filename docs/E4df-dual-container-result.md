# E4df：双容器双卡下 demand 触发真的会搬，但搬了更差（因为 0.86 还没到容量线）

日期：2026-10-28　后端：A = `<ASCEND-HOST>:31475`（`127.0.0.1:8110`，kv_both，kv_port 14579）
B = `<ASCEND-HOST>:31392`（pod `<POD>`，**<POD-G-POD>:8110**，kv_both，kv_port 14580，max-model-len 24576，util 0.80）
executor：`EXECUTOR_MODE=kv`、`MIGRATE_CARRIER=transfer`、`BALANCE=skew`、`HOT=0.75`、`COLD=0.55`、interval 5 s
负载：18 program × 3,200 词（≈5.2k token/个，需求 ≈94k = 单卡 114k 的 **0.82**），4 轮

## 结果

| 组 | 每轮 p50 (s) | sum_p50 | 搬家 | a 卡 demand | b 卡 demand |
|---|---|---|---|---|---|
| budget=2 | 2.08 / 1.63 / 1.65 / 1.65 | **7.015** | **7** | 0.857 → 0.809 | 0.0 → 0.048 |
| budget=4 | 2.08 / 1.59 / 1.61 / 1.66 | **6.939** | 0 | 0.857 恒定 | 0.0 |
| budget=8（重跑） | 1.71 / 1.65 / 1.60 / 1.59 | **6.555** | 0 | 0.856 恒定 | 0.0 |

（budget=8 第一次跑因 3 次请求超时未完成，重跑才拿到这行；单跑噪声不小，只能看趋势。）

## 三条结论

1. **demand 触发是有效的**：`usage={'a': 0.857, 'b': 0.0}` 越过 0.75，budget=2 那组真的把 7 个 program 搬过去（b 卡 demand 从 0 涨到 0.048）。这一条洗清了此前"平衡器从不触发"的疑虑——在两张卡都健康时它确实工作。
2. **但在这个操作点上搬家是净亏**：0.857 的 demand ≠ 真的装不下（容量线是 1.0），a 卡此时并没有在驱逐，搬过去的 7 个 program 只多付了 7 次 transfer 成本 → 最差的一臂（7.015 vs 6.555）。
3. **所以正确的门不是"demand > 0.75"，而是"demand > 1 且有驱逐证据"**（例如 `prefix_cache_hits_total / queries_total` 在下降，或 `kv_cache_usage` 贴着容量）。阈值 0.75 是为了"提前预警"，但预警提前到这里就是纯浪费。

## 对"定额要不要按需求算"的影响

- 这轮 budget 4 与 8 都是 0 次搬家（无空闲候选），所以**仍然无法用它验证定额**。
- 定额的证据仍然只有 M12b 的整数规划那一组：需求 144k / 容量 121k / 单个 9k ⇒ 需 `ceil(23/9)=3`，实测饱和在 4，边际收益 79k→127k→≈0。
- 结论降级为：**定额公式在"确实超容"时成立，但它必须挂在"确实超容"的判据下面**，否则搬得再多也只是搬运成本。

## 复现

```bash
# A 侧
bash /root/e2/start_both_a.sh          # kv_both, kv_port 14579
# B 侧（ssh -p <SSH-PORT>）
bash /root/e2/start_b_both.sh          # kv_both, kv_port 14580, <POD-G-POD>
# executor（A 侧）
EXECUTOR_BACKENDS="a=http://127.0.0.1:8110,b=http://<POD-G-POD>:8110" \
EXECUTOR_MODE=kv EXECUTOR_MIGRATE_CARRIER=transfer EXECUTOR_BALANCE=skew \
EXECUTOR_BALANCE_MOVE_BUDGET=2 python3 -m uvicorn executor.app:app --port 8100
BUD=2 N=18 WORDS=3200 TURNS=4 python3 /root/e2/e4d.py
```
