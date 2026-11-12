# kv_role=kv_both 双向搬运：一个分支 bug，六行补丁

日期：2026-10-28　宿主：A `coder-user-workplace-lg1-596f5d8846-75nts`（31475）、B `coder-user-residency-1-6c46f6d6c7-fnxpt`（10.244.1.9，32102）

## 结论先说

**双向通了**：同一对引擎（两侧都 `kv_role=kv_both`）互拉各一次，**external hits 100%**，拉取耗时 **0.18 s**。

| 方向 | 前缀 token | pull 耗时 | external hits / queries |
|---|---|---|---|
| A → B | 5,052 | 0.18 s | **5,052 / 5,052 = 100%** |
| B → A | 5,059 | 0.18 s | **5,059 / 5,059 = 100%** |

## 根因：不是组网限制，是一个 if/else

`/vllm-workspace/vllm-ascend/vllm_ascend/distributed/kv_transfer/kv_p2p/mooncake_connector.py` 的 `__init__`：

```python
if self.kv_role == "kv_producer":
    self.kv_send_thread = KVCacheSendingThread(...)   # 发送线程
    self.kv_send_thread.start()
else:
    self.kv_recv_thread = KVCacheRecvingThread(...)   # 只有接收
    self.kv_recv_thread.start()
```

`kv_both` 落进 `else` ⇒ **永远只起接收线程，没有发送线程**。对端来拉时，源端没人应答 → 拉取挂住（我们之前看到的就是这个）。

另外三处同样的角色判断会影响后续行为：等待就绪时选哪个线程、`get_finished` 分别报收发、以及加载错误的回报通道。

## 补丁（`patches/patch_kvboth_threads.py`，幂等，六处）

把这六处 `kv_role == "..."` 改成 `kv_role in ("...", "kv_both")`，并把 `else:` 拆成显式的 `if kv_role in ("kv_consumer", "kv_both")`。
`kv_producer` / `kv_consumer` 的行为不变（成员集合是超集）。

**验证补丁真的生效**：`kv_both` 引擎日志第一次出现 `KVCacheSendingThread started listening on path: ...`（补丁前两侧都只有 Recving 线程）。

## 顺手纠正一个我先前的误读

我说过“kv_both 下 `remote_block_ids` 只有 1 个、producer 下是 9 个”——**这是误读**。
`remote_block_ids` 是“按 block group 分层的列表”，长度 1 表示**只有一个 block group**，里面装着全部块：

```
[A] remote_block_ids type=list len=1 inner_lens=[40] num_prompt_blocks=40 block_size=128
```

40 个块、每块 128 token，与 4,699 token 的前缀吻合。producer 模式同样返回 1 个 group。所以“只报最后一块”的现象不存在，真正坏的是**发送线程根本没起**。

## 这条修好的意义

- 方向从“拓扑属性”变成“每次搬运的参数”：两台引擎同配置，谁搬谁不搬由请求里的 `kv_transfer_params` 决定。
- 不再需要为“目的地是谁”发愁：任意两台同构引擎都能互为源/目的。
- 代价没变：拉取 0.18 s / 5k token ≈ **26k token/s**，与生产/消费模式下的实测一致。

## 复现

```bash
# 两侧都打补丁并起 kv_both（kv_port 各自不同：14579 / 14581）
python3 patches/patch_kvboth_threads.py
bash start_both.sh            # 两侧同脚本，仅 kv_port 不同
DIR=a2b python3 probe_pull.py # 或 DIR=b2a
```

判据：`[B] external_prefix_cache_hits_total` 的增量应等于 `prefix_cache_queries_total` 的增量（199% 命中 ⇒ 真的从对端搬来，不是本地重算）。
