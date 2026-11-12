# TA 本体补丁 v1 验证：overcommit + program→shard hint

日期 2026-10-31　对象：`/root/m2/ThunderAgent`（TA 本体，钉 7ddc861 的克隆）　双卡：A=`127.0.0.1:8110`、B=`10.244.1.31:8110`（各 892 块 × 128 = 114,176）

## 1. 补丁内容（两个环境变量开关，默认关，改动幂等）

| 开关 | 位置 | 语义 |
|---|---|---|
| `TA_OVERCOMMIT=1` | `scheduler/router.py` | ①`_select_backend_for_new_program()` 无余量时按 `active_program_tokens` 最小者**放行**，全爆满则选最空 healthy 卡；②`update_program_before_request()` 两处 `await self._wait_for_resume(...)` 被 `if not _ta_overcommit()` 包住 → 不暂停、不挂 1800 s |
| `TA_HINT=1` + `TA_HINT_BACKENDS='a=http://…,b=http://…'` | 同上 + `scheduler/vllm_request_processor.py` | 请求体带 `program_id_hint`（或 `extra_body.program_id_hint`）时，把该 program 的 `backend_url` 直接改成目标卡：`unregister_program(old)` → `register_program(new)`，`self.hint_moves += 1`，日志 `[hint] <pid> -> <url> (moves=N)`；转发前把 `program_id_hint` 从 body 剥掉，避免 vLLM 400 |

## 2. 真机功能验证（TA 起在 A:9000，`TA_OVERCOMMIT=1 TA_HINT=1`）

| 请求 | hint | 结果 |
|---|---|---|
| r1 | a | → `127.0.0.1:8110` ✅ |
| r2 | a | → `127.0.0.1:8110` ✅（TA 本会往 B 摊，被 hint 拉回） |
| r3 | a | → `127.0.0.1:8110` ✅ |
| r4 | b | → `10.244.1.31:8110` ✅ |

`/programs` 与日志一致：`r1/r2/r3` 全在 A、`r4` 在 B；日志 `[hint] … (moves=1..4)` 共 4 条；`/health` 显示 `programs=4, paused=0`。

**v1 的坑（已修）**：第一版只在 `state.backend_url` 非空时生效，于是**新 program 的首个请求不吃 hint**（q1/q2 都 hint=a 却分别落在 A/B）。v2 把条件改成 `_tgt.url != (_cur or "")`，允许在“还没有 backend”时直接登记到 hint 指定的卡。

## 3. 这两个开关为什么是“控制 KV”的前提

TA 原来的行为链：放不下 → 排队 1800 s → `_pause_program()` 里 `unregister_program()` + `origin_backend` 清空 → `_resume_program()` 可能换卡 → 新卡没有该 program 的块 → 全量 prefill。**每暂停一次，就制造一次“KV 被丢弃”的机会。**

- `TA_OVERCOMMIT=1`：切断“暂停→换卡→重算”这条链，KV 留在原卡；
- `TA_HINT=1`：放置权交给调用方（我们的驻留策略），换卡从“随机换”变成“按 KV 位置换”；
- 两者合起来才谈得上“**主动控制 KV**”，而不是被动等 LRU。

## 4. 还没做的（下一步）

1. **hint 与 KV 真正联动**：hint 改变后，目标卡若没有该前缀，先由执行器 `capture+pull`（M6 已验 1.82×）或 recompute 预热，再让 hint 生效 —— 目前 hint 只是换账本，不搬块。
2. **保活**：`TA_OVERCOMMIT=1` 不阻止 vLLM 因物理容量淘汰；要“不许丢”仍需 1-token ping（M11：0/10→10/10，代价 3 倍 prefill 计数）。
3. **四臂实验**：`TA 默认` / `TA+overcommit` / `+常量 hint` / `+hint 由驻留信号驱动`，指标 `paused 峰值 / 集群命中 / token-s`，在 32-program 真实 agent 负载上跑。

## 5. 回滚

```bash
cd /root/m2/ThunderAgent/scheduler && cp router.py.bak2 router.py && cp vllm_request_processor.py.bak2 vllm_request_processor.py
```
（`router.py.bak` 是更早一版，`.bak2` 是本次补丁前。）
