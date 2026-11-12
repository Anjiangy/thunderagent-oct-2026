# E-env — 跨容器 p2p KV 搬运：通过

日期：2026-10-27
环境：**两个独立容器、各一张 910B2、各一条 SSH**（这是 v2 路线要求的新拓扑）

| 角色 | 容器 | IP | 卡 | vLLM |
|---|---|---|---|---|
| A（producer，prefill 端） | `coder-user-workplace-lg1-747c9f97d-x9qxc` | 10.244.1.62 | NPU3 | 0.23.0 |
| B（consumer，decode 端） | `coder-user-residency-1-7c755956f9-zlnct` | 10.244.1.54 | NPU2 | 0.23.0 |

两侧：`--max-model-len 8192 --gpu-memory-utilization 0.80 --enable-prefix-caching --enforce-eager`，
`--kv-transfer-config '{"kv_connector":"MooncakeConnectorV1","kv_role":"kv_producer|kv_consumer","kv_buffer_device":"npu","kv_port":14579|14580,...}'`。
单卡 KV = 892 块 × 128 = **114,176 token**。

## 结果

| 指标 | 值 |
|---|---|
| 容器间 TCP（B:8110 / A:14579） | 双向 open |
| 冷 prefill（B，稳态 3 次） | **0.226 / 0.226 / 0.225 s** |
| 源端 prefill（A，出 transfer handle） | 0.226~0.234 s |
| **搬运（A→B，含网络）** | **0.139 / 0.138 / 0.139 s** |
| 外部 KV 命中 | 1706 / 1692 / 1701（**等于 prompt token 数，100%**） |
| `c_mig / c_rec` | **0.61** |

判据（写在 v2 路线里）：`c_mig ≤ 0.3 s` → **0.139 s，通过**。

## 三条证据（缺一不可）

1. B 侧日志：`Connected to segment: 10.244.1.62:20338`、`KV cache transfer for request ... took 228.43 ms. local_ip 10.244.1.54 remote_session_id 10.244.1.62:16410`；
2. A 侧日志：`Delaying free of 14 blocks for request ...`（源端确实把块留住了等对方取）；
3. **`vllm:external_prefix_cache_hits_total` 增量 == prompt token 数**（1706/1692/1701），且 B 从未见过这些 prompt。

## 一个必须记住的度量坑

搬运来的块计入 **`vllm:external_prefix_cache_hits_total`**，**不计入** `vllm:prefix_cache_hits_total`。
第一版脚本只读后者 → 读到 `dh=0`，差点误判成"搬运失败"。E1/E2 的仪表必须两个计数器都读。

## 对路线的意义

- **主动搬迁在这套"一卡一容器"环境里可行**：移动的边际成本 ≈ 0.6 次重算，与此前同机同进程（约 0.5~0.6）几乎一致 → 容器边界没有带来可见开销（0.139 s / 1700 token ≈ 82 µs/token，与同机 82 µs/token 相同）。
- 因此 §3 的不等式可以直接沿用：`c_mig ≈ 0.6·c_rec`，`N·q ≥ 2` 的判据成立，阈值上调一点即可。
- 下一步（E0/E1）可以按计划走：E1 只需 **1 卡**，可直接在 B 容器上做。

## 复现

```bash
# 两侧各一
bash /root/env/start.sh producer 8110 14579   # A
bash /root/env/start.sh consumer 8110 14580   # B
# 在 A 里跑度量（脚本会跨容器打 B）
python3 /root/env/e_env2.py
```
